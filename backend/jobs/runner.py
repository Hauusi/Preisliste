"""Hintergrundjobs: ein Worker-Thread im App-Prozess, Jobs nacheinander, Fortschritt und Abbruch.

Fortschritt laufender Jobs liegt im Speicher (ein Prozess), weil ein Job während eines großen Imports
eine Schreibsperre auf SQLite hält. Am Ende wird er in die Tabelle jobs geschrieben.
Das Abbruch-Flag wird aus der Datenbank gelesen (Lesen ist im WAL-Modus trotz Schreibsperre möglich).
"""

from __future__ import annotations

import logging
import threading
import traceback
from typing import Callable

from sqlalchemy import event, select

from backend.config import Settings
from backend.database.engine import session_scope
from backend.models.entities import Job, User, utcnow

log = logging.getLogger("preisliste.jobs")

JOB_LABELS = {
    "IMPORT": "Import",
    "AI_COLUMNS": "KI-Spaltenvorschlag",
    "AI_MATCH": "KI-Zuordnung",
    "AI_UPDATE_MATCH": "KI-Prüfung Jahresabgleich",
    "AI_RULE": "KI-Regelvorschlag",
}


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: int, settings: Settings):
        self.job_id = job_id
        self.settings = settings

    def progress(self, done: int, total: int | None = None, message: str | None = None) -> None:
        with _live_lock:
            live = _live.setdefault(self.job_id, {"progress": 0, "total": 0, "message": None})
            live["progress"] = done
            if total is not None:
                live["total"] = total
            if message is not None:
                live["message"] = message[:500]

    def check_cancel(self) -> None:
        with session_scope() as db:
            if db.scalar(select(Job.cancel_requested).where(Job.id == self.job_id)):
                raise JobCancelled()


Handler = Callable[[JobContext, dict], dict | None]
HANDLERS: dict[str, Handler] = {}
_wakeup = threading.Event()
_live: dict[int, dict] = {}
_live_lock = threading.Lock()


def live_progress(job: Job) -> dict:
    """Fortschritt eines Jobs: im Speicher, solange er läuft, sonst aus der Datenbank."""
    with _live_lock:
        live = dict(_live.get(job.id, {}))
    if job.status == "LAEUFT" and live:
        return live
    return {"progress": job.progress, "total": job.total, "message": job.message}


def handler(job_type: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


def enqueue(db, job_type: str, params: dict, user: User) -> Job:
    if job_type not in JOB_LABELS:
        raise ValueError(f"Unbekannter Jobtyp {job_type}")
    job = Job(type=job_type, params=params, created_by=user.id, status="WARTEND")
    db.add(job)
    db.flush()
    # Worker erst nach dem Commit wecken, sonst sieht er den Job noch nicht
    event.listen(db, "after_commit", lambda _s: _wakeup.set(), once=True)
    return job


def request_cancel(db, job: Job) -> None:
    if job.status in ("WARTEND", "LAEUFT"):
        job.cancel_requested = True
        if job.status == "WARTEND":
            job.status = "ABGEBROCHEN"
            job.finished_at = utcnow()
            job.message = "Vor dem Start abgebrochen"


def run_job(job_id: int, settings: Settings) -> None:
    from backend.jobs import handlers  # noqa: F401 - registriert die Handler

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "WARTEND":
            return
        job.status, job.started_at = "LAEUFT", utcnow()
        job_type, params = job.type, dict(job.params or {})
    ctx = JobContext(job_id, settings)
    try:
        result = HANDLERS[job_type](ctx, params)
        status, message = "FERTIG", None
    except JobCancelled:
        result, status, message = None, "ABGEBROCHEN", "Abgebrochen"
    except Exception as exc:  # Fehler sichtbar machen, Worker läuft weiter
        log.error("Job %s fehlgeschlagen:\n%s", job_id, traceback.format_exc())
        result, status, message = None, "FEHLER", str(exc)[:500] or type(exc).__name__
    with _live_lock:
        live = _live.pop(job_id, {})
    with session_scope() as db:
        job = db.get(Job, job_id)
        job.status, job.finished_at = status, utcnow()
        job.progress, job.total = live.get("progress", 0), live.get("total", 0)
        job.message = message or live.get("message")
        if result is not None:
            job.result = result
    on_finished = HANDLERS.get(f"{job_type}:finally")
    if on_finished:
        on_finished(ctx, {**params, "_status": status, "_message": message})


def run_pending(settings: Settings) -> int:
    """Alle wartenden Jobs direkt ausführen (Tests, CLI)."""
    count = 0
    while True:
        with session_scope() as db:
            job_id = db.scalar(select(Job.id).where(Job.status == "WARTEND").order_by(Job.id).limit(1))
        if job_id is None:
            return count
        run_job(job_id, settings)
        count += 1


def recover_after_restart() -> None:
    with session_scope() as db:
        for job in db.scalars(select(Job).where(Job.status == "LAEUFT")):
            job.status, job.finished_at = "FEHLER", utcnow()
            job.message = "Durch Neustart des Servers abgebrochen"
    from backend.jobs import handlers

    handlers.recover_price_lists()


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                if run_pending(self.settings) == 0:
                    _wakeup.wait(timeout=2)
                    _wakeup.clear()
            except Exception:  # pragma: no cover - darf den Worker nie beenden
                log.error("Worker-Fehler:\n%s", traceback.format_exc())
                self._stop.wait(timeout=5)

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        _wakeup.set()
        self.thread.join(timeout)


def start_worker(settings: Settings) -> Worker:
    worker = Worker(settings)
    worker.thread.start()
    return worker
