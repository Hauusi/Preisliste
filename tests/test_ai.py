import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import select

from backend.ai.provider import (
    AIInvalidResponse, MockProvider, OllamaProvider, cached_status, set_provider,
)
from backend.ai.schemas import ColumnSuggestion
from backend.config import Settings
from backend.database.engine import session_scope
from backend.jobs.runner import enqueue, recover_after_restart, request_cancel, run_pending
from backend.models.entities import AiMatchSuggestion, ComparisonItem, Job, PriceList, User
from tests.conftest import make_xlsx, run_jobs
from tests.test_group_b_web import import_list
from tests.test_import_web import upload

S = Settings(ai_retries=2)


def test_valid_response():
    m = MockProvider(S, ['{"columns": [{"index": 0, "field": "article_number"}], "confidence": 0.9}'])
    s = m.suggest_columns(["Nr", "Preis"], [["A", 1]])
    assert s.columns[0].field == "article_number"



def test_retry_succeeds_on_third_attempt():
    m = MockProvider(S, ["kein json", '{"columns": [], "confidence": 2}',
                         '{"columns": [{"index": 1, "field": "list_price"}], "confidence": 0.5}'])
    s = m.suggest_columns(["Nr", "Preis"], [])
    assert s.columns[0].field == "list_price" and len(m.prompts) == 3


@pytest.mark.parametrize("bad", [
    "kein json",
    '{"columns": [{"index": 0, "field": "rm -rf"}], "confidence": 0.5}',  # unbekanntes Feld
    '{"columns": [{"index": 9, "field": "list_price"}], "confidence": 0.5}',  # Index außerhalb
    '{"columns": [{"index": 0, "field": "list_price"}, {"index": 1, "field": "list_price"}], "confidence": 0.5}',
    '{"columns": [], "confidence": 0.5, "code": "import os"}',  # Zusatzfeld
])
def test_invalid_responses_become_unclear(bad):
    m = MockProvider(S, [bad] * 3)
    with pytest.raises(AIInvalidResponse):
        m.suggest_columns(["Nr", "Preis"], [])
    assert len(m.prompts) == 3  # begrenzte Wiederholung


def test_judge_match_rejects_unknown_candidate():
    resp = json.dumps({"new_article": "N1", "old_article": "ERFUNDEN", "match": True, "confidence": 0.9, "reason": "x"})
    m = MockProvider(S, [resp] * 3)
    with pytest.raises(AIInvalidResponse):
        m.judge_match({"artikelnummer": "N1"}, [{"artikelnummer": "O1"}])


def test_only_small_excerpt_is_sent():
    m = MockProvider(S, ['{"columns": [], "confidence": 0.1}'])
    rows = [[f"R{i}", i] for i in range(100)]
    m.suggest_columns(["Nr", "Preis"], rows)
    assert "R4" in m.prompts[0] and "R5" not in m.prompts[0]


def test_non_local_endpoint_rejected():
    with pytest.raises(ValueError, match="nicht lokal"):
        OllamaProvider(Settings(ollama_url="https://api.example.com"))
    st = cached_status(Settings(ai_provider="ollama", ollama_url="https://evil.example"), max_age=0)
    assert not st.active and "nicht lokal" in st.message


class FakeOllama(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "llama3.2:3b"}]})
        elif self.path == "/api/ps":
            self._send({"models": [{"size": 2_500_000_000}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append(payload)
        content = json.dumps({"columns": [{"index": 0, "field": "article_number"}], "confidence": 0.7})
        self._send({"message": {"role": "assistant", "content": content}})


def test_ollama_provider_against_fake_server():
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        p = OllamaProvider(Settings(ollama_url=f"http://127.0.0.1:{server.server_port}"))
        st = p.status()
        assert st.active and st.loaded_mb == 2384
        s = p.suggest_columns(["Art.-Nr."], [["A1"]])
        assert s.columns[0].field == "article_number"
        req = FakeOllama.requests[-1]
        assert req["model"] == "llama3.2:3b" and req["stream"] is False
        assert req["format"] == ColumnSuggestion.model_json_schema()  # Structured Outputs
        assert req["options"]["temperature"] == 0
    finally:
        server.shutdown()


def test_ollama_unreachable_status():
    st = OllamaProvider(Settings(ollama_url="http://127.0.0.1:9")).status()
    assert not st.active and "nicht erreichbar" in st.message


# ---------- Jobs und Web ----------

def test_ai_buttons_hidden_without_ai(admin_client, tmp_path):
    p = make_xlsx(tmp_path / "l.xlsx", [["Code", "Text"], ["A", "x"]])
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    page = admin_client.get(f"/import/{list_id}").text
    assert "KI-Vorschlag" not in page and "KI inaktiv" in page


def test_ai_columns_job(admin_client, tmp_path, app):
    set_provider(MockProvider(S, ['{"columns": [{"index": 0, "field": "article_number"}, '
                                  '{"index": 1, "field": "supplier_price"}], "manufacturer": "ACME", "confidence": 0.6}']))
    p = make_xlsx(tmp_path / "l.xlsx", [["Code", "Wert", "Text"], ["AB-1", "1,00", "x"], ["CD-2", "2,00", "y"]])
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    page = admin_client.get(f"/import/{list_id}").text
    assert "KI-Vorschlag für Spalten holen" in page and "KI aktiv" in page
    r = admin_client.post(f"/import/{list_id}/ki-spalten", data={"csrf_token": admin_client.csrf, "sheet": "Preise",
                                                                 "header_row": "1", "header_rows": "1"},
                          follow_redirects=False)
    job_url = r.headers["location"]
    run_jobs(app)
    job_page = admin_client.get(job_url).text
    assert "FERTIG" in job_page
    link = job_page.split('class="button" href="')[1].split('"')[0].replace("&amp;", "&")
    page = admin_client.get(link).text
    assert "KI-Vorschlag übernommen" in page and "ACME" in page
    # Spalte 0 hatte keine Erkennung -> KI-Vorschlag vorausgewählt und markiert
    assert re.search(r'name="col_0">.*?<option value="article_number" selected.*?<small class="UNKLAR">KI</small>', page, re.S)
    # Spalte 1 wurde von der Heuristik als Preis erkannt -> KI überschreibt nicht, zeigt nur ihre Meinung
    assert "KI meint: Einkaufspreis (EK)" in page


def _setup_comparison(admin_client, tmp_path):
    old = import_list(admin_client, tmp_path, "alt", [
        ["Art.-Nr.", "Bezeichnung", "Listenpreis"],
        ["ABC-1000", "Spezialteil Typ X", "5,00"], ["OLD-77", "Akku-Bohrschrauber 18V", "99,00"],
    ])
    new = import_list(admin_client, tmp_path, "neu", [
        ["Art.-Nr.", "Bezeichnung", "Listenpreis"],
        ["ABC-1001", "Spezialteil Typ X", "6,00"], ["NEW-99", "Bohrschrauber Akku 18 Volt", "109,00"],
    ])
    r = admin_client.post("/vergleiche", data={"csrf_token": admin_client.csrf, "old_id": old, "new_id": new,
                                               "price_type": "LISTE", "quantity": "1"}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_ai_match_job_suggests_never_assigns(admin_client, tmp_path, app):
    cmp_id = _setup_comparison(admin_client, tmp_path)
    with session_scope() as db:
        st = {i.article_number: i.status for i in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id))}
    assert st == {"ABC-1001": "NICHT_EINDEUTIG", "NEW-99": "NEUER_ARTIKEL", "OLD-77": "ENTFALLENER_ARTIKEL"}

    responses = [
        json.dumps({"new_article": "ABC-1001", "old_article": "ABC-1000", "match": True, "confidence": 0.8, "reason": "gleiche Bezeichnung"}),
        json.dumps({"new_article": "NEW-99", "old_article": "OLD-77", "match": True, "confidence": 0.7, "reason": "Nachfolger"}),
    ]
    mock = MockProvider(S, responses)
    set_provider(mock)
    r = admin_client.post(f"/vergleiche/{cmp_id}/ki", data={"csrf_token": admin_client.csrf}, follow_redirects=False)
    assert r.headers["location"].startswith("/jobs/")
    run_jobs(app)
    with session_scope() as db:
        items = {i.article_number: i for i in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id))}
        assert db.scalar(select(Job).order_by(Job.id.desc())).result["treffer"] == 2
    # Nichts automatisch übernommen
    assert items["ABC-1001"].status == "NICHT_EINDEUTIG"
    assert items["ABC-1001"].candidates[0]["ki"]["status"] == "TREFFER"
    assert items["NEW-99"].status == "NICHT_EINDEUTIG" and items["NEW-99"].match_method == "KI"
    assert "OLD-77" not in items  # nicht mehr als entfallen gezählt, solange unentschieden
    # Nur Ausschnitte gesendet
    assert all("Listenpreis" not in pr and "99,00" not in pr for pr in mock.prompts)
    page = admin_client.get(f"/vergleiche/{cmp_id}").text
    assert "KI: passt" in page
    # Benutzer bestätigt den KI-Vorschlag
    r = admin_client.post(f"/vergleiche/{cmp_id}/eintrag/{items['NEW-99'].id}",
                          data={"csrf_token": admin_client.csrf, "old_id": items["NEW-99"].candidates[0]["old_id"]},
                          follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as db:
        st = {i.article_number: (i.status, i.match_method) for i in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id))}
    assert st["NEW-99"] == ("PREIS_ERHOEHT", "BESTAETIGT")


def test_ai_match_invalid_answers_are_unclear(admin_client, tmp_path, app):
    cmp_id = _setup_comparison(admin_client, tmp_path)
    set_provider(MockProvider(S, ["unsinn"] * 10))
    admin_client.post(f"/vergleiche/{cmp_id}/ki", data={"csrf_token": admin_client.csrf})
    run_jobs(app)
    with session_scope() as db:
        sugg = db.scalars(select(AiMatchSuggestion)).all()
        assert sugg and all(s.status == "UNKLAR" for s in sugg)
        items = {i.article_number: i.status for i in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id))}
    assert items["NEW-99"] == "NEUER_ARTIKEL"


def test_ai_match_fails_cleanly_when_ai_inactive(admin_client, tmp_path, app):
    cmp_id = _setup_comparison(admin_client, tmp_path)
    set_provider(MockProvider(S, [], active=False))
    admin_client.post(f"/vergleiche/{cmp_id}/ki", data={"csrf_token": admin_client.csrf})
    run_jobs(app)
    with session_scope() as db:
        job = db.scalar(select(Job).order_by(Job.id.desc()))
    assert job.status == "FEHLER" and "inaktiv" in job.message


class CancellingMock(MockProvider):
    def _complete(self, system, prompt, schema):
        out = super()._complete(system, prompt, schema)
        with session_scope() as db:
            db.scalar(select(Job).where(Job.status == "LAEUFT")).cancel_requested = True
        return out


def test_cancel_running_job(admin_client, tmp_path, app):
    cmp_id = _setup_comparison(admin_client, tmp_path)
    resp = json.dumps({"new_article": "ABC-1001", "old_article": "ABC-1000", "match": True, "confidence": 0.8, "reason": "x"})
    set_provider(CancellingMock(S, [resp, resp]))
    admin_client.post(f"/vergleiche/{cmp_id}/ki", data={"csrf_token": admin_client.csrf})
    run_jobs(app)
    with session_scope() as db:
        job = db.scalar(select(Job).order_by(Job.id.desc()))
        assert job.status == "ABGEBROCHEN" and job.progress == 1 and job.total == 2
        assert len(db.scalars(select(AiMatchSuggestion)).all()) == 1


def test_cancel_waiting_job_and_restart_recovery(app):
    with session_scope() as db:
        admin = db.scalar(select(User))
        j1 = enqueue(db, "AI_RULE", {"text": "x"}, admin)
        request_cancel(db, j1)
        j2 = enqueue(db, "AI_RULE", {"text": "y"}, admin)
        j2.status = "LAEUFT"
        pl = PriceList(name="p", source_file="p", stored_file="p", file_sha256="0" * 64, uploaded_by=admin.id,
                       status="WARTESCHLANGE")
        db.add(pl)
        db.flush()
        ids = (j1.id, j2.id, pl.id)
    recover_after_restart()
    with session_scope() as db:
        assert db.get(Job, ids[0]).status == "ABGEBROCHEN"
        assert db.get(Job, ids[1]).status == "FEHLER"
        assert db.get(PriceList, ids[2]).status == "ENTWURF"


def test_ai_rule_suggestion(admin_client, app):
    good = json.dumps({"start_price": "LISTE", "explanation": "Rabatt dann Transport",
                       "steps": [{"type": "discount", "percent": "15", "base": "start"},
                                 {"type": "surcharge", "percent": "4", "base": "current"}]})
    set_provider(MockProvider(S, [good]))
    r = admin_client.post("/regeln/ki", data={"csrf_token": admin_client.csrf, "text": "15 % Rabatt, 4 % Transport"},
                          follow_redirects=False)
    run_jobs(app)
    job_id = r.headers["location"].rsplit("/", 1)[1]
    page = admin_client.get(f"/regeln/neu?ki_job={job_id}").text
    assert "Vorschlag der KI, noch nicht gespeichert" in page
    assert 'name="step_1_value" value="15"' in page
    from backend.models.entities import Rule
    with session_scope() as db:
        assert db.scalar(select(Rule)) is None  # nichts gespeichert


def test_ai_rule_invalid_suggestion_is_unclear(admin_client, app):
    bad = json.dumps({"start_price": "LISTE", "explanation": "x", "steps": [{"type": "discount", "percent": "500"}]})
    set_provider(MockProvider(S, [bad]))
    r = admin_client.post("/regeln/ki", data={"csrf_token": admin_client.csrf, "text": "x"}, follow_redirects=False)
    run_jobs(app)
    page = admin_client.get(r.headers["location"]).text
    assert "UNKLAR" in page


def test_job_access_restricted(admin_client, user_client, app):
    set_provider(MockProvider(S, ["{}"]))
    r = admin_client.post("/regeln/ki", data={"csrf_token": admin_client.csrf, "text": "x"}, follow_redirects=False)
    assert user_client.get(r.headers["location"]).status_code == 404


def test_real_worker_thread_picks_up_job_quickly(app, settings):
    import time

    from backend.jobs.runner import start_worker

    set_provider(MockProvider(S, ['{"start_price": "LISTE", "explanation": "x", "steps": [{"type": "fixed", "amount": "1"}]}']))
    worker = start_worker(settings)
    try:
        with session_scope() as db:
            job_id = enqueue(db, "AI_RULE", {"text": "x"}, db.scalar(select(User))).id
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            with session_scope() as db:
                status = db.get(Job, job_id).status
            if status == "FERTIG":
                break
            time.sleep(0.1)
        assert status == "FERTIG"
    finally:
        worker.stop()
    assert not worker.thread.is_alive()
