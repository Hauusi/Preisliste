"""KI-Einschätzung im Jahresabgleich: geänderte Artikelnummern nur vorschlagen, nie automatisch übernehmen."""

import json

import pytest
from decimal import Decimal

from sqlalchemy import select

from backend.ai.provider import MockProvider, set_provider
from backend.config import Settings
from backend.database.engine import session_scope
from backend.models.entities import Job, MatchDecision
from tests.conftest import run_jobs
from tests.test_annual_extras import _start
from tests.test_price_update import _import, _items, _ours, _setup

D = Decimal
S = Settings(ai_retries=2)


@pytest.fixture(autouse=True)
def _reset_provider():
    yield
    set_provider(None)


def _scenario(c, app, tmp_path):
    mid, rule_id = _setup(c)
    ours = _ours(c, app, tmp_path, mid, [["LED1", "Leuchte Nova 10W", "10,00", "20,00"],
                                         ["N20", "Leuchte Nova 20W", "10,00", "20,00"],
                                         ["ZZZ9", "Kabel", "5,00", "10,00"]])
    new = _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"],
                                          ["LED1", "Leuchte Nova 10W", "10,00"],
                                          ["QX-7781", "Leuchte Nova 20W", "11,00"],
                                          ["LED3", "Leuchte Nova 30W", "30,00"]], mid, "HERSTELLER")
    return _start(c, ours, new, rule_id)


def test_ai_suggests_renamed_article_and_user_confirms(admin_client, tmp_path, app):
    c = admin_client
    url = _scenario(c, app, tmp_path)
    _, items = _items()
    assert items["N20"].status == "NICHT_IN_HERSTELLERLISTE"
    page = c.get(url).text
    assert "Artikel fehlen beim Hersteller oder sind unklar" in page and "KI inaktiv" in page

    mock = MockProvider(S, [
        json.dumps({"new_article": "N20", "old_article": "QX-7781", "match": True, "confidence": 0.9,
                    "reason": "Gleiche Bezeichnung, Nummer nur um -A ergänzt"}),
        json.dumps({"new_article": "ZZZ9", "old_article": None, "match": False, "confidence": 0.8,
                    "reason": "Kein Kabel in der Liste"}),
    ])
    set_provider(mock)
    assert "KI prüfen lassen" in c.get(url).text
    r = c.post(url + "/ki", data={"csrf_token": c.csrf}, follow_redirects=False)
    assert r.headers["location"].startswith("/jobs/")
    run_jobs(app)
    with session_scope() as db:
        assert db.scalar(select(Job).order_by(Job.id.desc())).result["treffer"] == 1
    _, items = _items()
    led2 = items["N20"]
    # nichts automatisch übernommen
    assert led2.status == "NICHT_IN_HERSTELLERLISTE" and led2.final_ek == D("10.00")
    assert led2.ai_hint["status"] == "TREFFER" and led2.ai_hint["number"] == "QX-7781"
    assert items["ZZZ9"].ai_hint["status"] == "KEIN_TREFFER" and "Kein ähnlicher Artikel" in items["ZZZ9"].ai_hint["reason"]
    assert len(mock.prompts) == 1  # ohne ähnliche Kandidaten wird die KI nicht gefragt
    # nur Nummer/Bezeichnung gesendet, keine Preise; LED1 (schon zugeordnet) kein Kandidat
    assert all("11,00" not in p and "11.00" not in p and '"LED1"' not in p for p in mock.prompts)
    page = c.get(url).text
    assert "KI meint:" in page and "RAQX-7781" in page and "Gleiche Bezeichnung" in page

    c.post(f"{url}/positionen/{led2.id}", data={"csrf_token": c.csrf, "action": "ki_uebernehmen"})
    _, items = _items()
    led2 = items["N20"]
    assert (led2.status, led2.final_ek, led2.final_vk, led2.match_method) == ("PRUEFEN", D("11.00"), D("22.00"), "BESTAETIGT")  # +10 % = Prüfschwelle
    assert led2.ai_hint["status"] == "UEBERNOMMEN"
    with session_scope() as db:
        assert db.scalar(select(MatchDecision)).decision == "MATCH"


def test_ai_hint_can_be_rejected(admin_client, tmp_path, app):
    c = admin_client
    url = _scenario(c, app, tmp_path)
    set_provider(MockProvider(S, [
        json.dumps({"new_article": "N20", "old_article": "QX-7781", "match": True, "confidence": 0.6, "reason": "ähnlich"}),
        json.dumps({"new_article": "ZZZ9", "old_article": None, "match": False, "confidence": 0.8, "reason": "nein"}),
    ]))
    c.post(url + "/ki", data={"csrf_token": c.csrf})
    run_jobs(app)
    _, items = _items()
    c.post(f"{url}/positionen/{items['N20'].id}", data={"csrf_token": c.csrf, "action": "ki_ablehnen"})
    _, items = _items()
    assert items["N20"].ai_hint["status"] == "ABGELEHNT" and items["N20"].status == "NICHT_IN_HERSTELLERLISTE"
    with session_scope() as db:
        assert db.scalar(select(MatchDecision)).decision == "NO_MATCH"
    # abgelehnter Kandidat wird beim nächsten KI-Lauf nicht mehr vorgeschlagen
    from backend.jobs.handlers import update_targets
    with session_scope() as db:
        targets = dict(update_targets(db, items["N20"].update_id))
    assert items["N20"].id not in targets or all(t != items["N20"].source_article_id for t in targets[items["N20"].id])
    r = c.post(f"{url}/positionen/{items['N20'].id}", data={"csrf_token": c.csrf, "action": "ki_uebernehmen"})
    assert "keinen Treffer vorgeschlagen" in r.text
