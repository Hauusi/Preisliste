from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.database.engine import get_db
from backend.jobs.runner import JOB_LABELS, live_progress, request_cancel
from backend.models.entities import Job, User
from backend.services.audit import audit

router = APIRouter()


def _job(db: Session, job_id: int, user: User) -> Job:
    job = db.get(Job, job_id)
    if job is None or (job.created_by != user.id and user.role != "admin"):
        raise HTTPException(404, "Job nicht gefunden")
    return job


def result_link(job: Job) -> tuple[str, str] | None:
    r = job.result or {}
    p = job.params or {}
    if job.status != "FERTIG":
        if job.type == "IMPORT":
            return f"/import/{p.get('price_list_id')}", "Zurück zur Import-Vorschau"
        return None
    if job.type == "IMPORT" and r.get("update_id"):
        return f"/aktualisierungen/{r['update_id']}", "Ergebnis prüfen →"
    if job.type == "IMPORT" and r.get("kind") == "UNSERE":
        return f"/listen/{r.get('price_list_id')}?neu=1", "Zur Liste →"
    if job.type == "IMPORT":
        # Nächster Schritt im Ablauf: kalkulieren (bei aufgeteilter Datei die neue Liste)
        target = (r.get("price_list_ids") or [r.get("price_list_id")])[-1]
        return f"/listen/{target}/kalkulation", "Weiter: Kalkulieren →"
    if job.type == "AI_COLUMNS":
        query = urlencode({"sheet": p.get("sheet"), "header_row": p.get("header_row"),
                           "header_rows": p.get("header_rows", 1), "ki_job": job.id})
        return f"/import/{p.get('price_list_id')}/spalten?{query}", "Vorschlag in der Vorschau anzeigen"
    if job.type == "AI_RULE":
        return f"/regeln/neu?ki_job={job.id}", "Vorschlag im Regel-Editor öffnen"
    if job.type == "AI_MATCH":
        return f"/vergleiche/{p.get('comparison_id')}?status=NICHT_EINDEUTIG", "Unklare Fälle prüfen"
    if job.type == "AI_UPDATE_MATCH":
        return f"/aktualisierungen/{p.get('update_id')}?status=offen", "KI-Einschätzungen ansehen"
    return None


def _auto_go(job: Job) -> bool:
    """Nach dem Import automatisch weiter zum Ergebnis (Abgleich bzw. neue eigene Liste)."""
    r = job.result or {}
    return job.type == "IMPORT" and job.status == "FERTIG" and bool(r.get("update_id") or r.get("kind") == "UNSERE")


@router.get("/jobs")
def jobs(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Job).order_by(Job.id.desc()).limit(100)
    if user.role != "admin":
        stmt = stmt.where(Job.created_by == user.id)
    return render(request, "jobs.html", {"jobs": db.scalars(stmt).all(), "labels": JOB_LABELS})


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = _job(db, job_id, user)
    return render(request, "job.html", {"job": job, "labels": JOB_LABELS, "link": result_link(job),
                                        "step": 3 if job.type == "IMPORT" else None, "auto_go": _auto_go(job),
                                        "running": job.status in ("WARTEND", "LAEUFT"), "live": live_progress(job)})


@router.get("/api/jobs/{job_id}")
def job_json(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = _job(db, job_id, user)
    live = live_progress(job)
    return {"id": job.id, "typ": job.type, "status": job.status, "fortschritt": live["progress"],
            "gesamt": live["total"], "meldung": live["message"], "ergebnis": job.result}


@router.post("/jobs/{job_id}/abbrechen", dependencies=[Depends(check_csrf)])
def cancel(request: Request, job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = _job(db, job_id, user)
    request_cancel(db, job)
    audit(db, user, "job_abgebrochen", "job", job.id, {"typ": job.type}, client_ip(request))
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
