"""Kompletter Ablauf: Hochladen -> Spalten -> Hersteller/Währung -> Import -> Kalkulieren -> Ergebnis."""

import re

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import Manufacturer
from tests.conftest import make_xlsx, run_jobs
from tests.test_import_web import upload


def test_full_wizard(admin_client, tmp_path, app):
    c = admin_client
    c.post("/hersteller", data={"csrf_token": c.csrf, "name": "Redtronic", "code": "RT"})
    with session_scope() as db:
        mid = db.scalar(select(Manufacturer)).id

    # Schritt 1
    page = c.get("/import").text
    assert 'class="current"><span>1</span>Datei' in page
    p = make_xlsx(tmp_path / "rt_2026.xlsx", [["Art.-Nr.", "Bezeichnung", "EK"], ["100", "Platine", "10,00"],
                                              ["200", "Kabel", "2,50"]])
    r = upload(c, p)
    step2 = r.headers["location"]

    # Schritt 2
    page = c.get(step2).text
    assert 'class="current"><span>2</span>Prüfen' in page and "Alles erkannt" in page
    assert "Weiter: Prüfen" in c.get(step2 + "/spalten").text  # Spalten von Hand anpassen
    list_id = int(step2.rsplit("/", 1)[1])
    r = c.post(f"/import/{list_id}/spalten", data={"csrf_token": c.csrf, "sheet": "Preise", "header_row": "1",
                                                   "col_0": "article_number"})
    assert r.status_code == 400 and "Preisspalte" in r.text  # bleibt in Schritt 2
    r = c.post(f"/import/{list_id}/spalten", data={"csrf_token": c.csrf, "sheet": "Preise", "header_row": "1",
                                                   "col_0": "article_number", "col_1": "description",
                                                   "col_2": "supplier_price", "sep_2": ","}, follow_redirects=False)
    assert r.status_code == 303

    # Schritt 3: EUR ist vorausgewählt, Hersteller fehlt -> Fehler bleibt in Schritt 3
    page = c.get(f"/import/{list_id}/hersteller").text
    assert 'class="current"><span>2</span>' in page and '<option value="EUR" selected>' in page
    hidden = dict(re.findall(r'<input type="hidden" name="((?:col|sep)_\d+|sheet|header_rows?)" value="([^"]*)">', page))
    r = c.post(f"/import/{list_id}/confirm", data={"csrf_token": c.csrf, **hidden, "currency": "EUR"})
    assert r.status_code == 400 and "Hersteller wählen" in r.text  # alter Weg bleibt
    r = c.post(f"/import/{list_id}/confirm", data={"csrf_token": c.csrf, **hidden, "currency": "EUR",
                                                   "manufacturer_id": str(mid)}, follow_redirects=False)
    job_url = r.headers["location"]

    # Schritt 4
    run_jobs(app)
    page = c.get(job_url).text
    assert 'class="current"><span>3</span>' in page
    next_url = re.search(r'<a class="button" href="([^"]+)">Weiter: Kalkulieren', page).group(1)
    assert next_url == f"/listen/{list_id}/kalkulation"

    # Schritt 5 ohne Regel: Link zum Regel-Editor mit Rücksprung
    page = c.get(next_url).text
    assert 'class="current"><span>3</span>' in page and "noch keine Kalkulationsregel" in page
    rule_url = re.search(r'href="(/regeln/neu\?[^"]+)"', page).group(1).replace("&amp;", "&")
    page = c.get(rule_url).text
    assert 'value="Redtronic"' in page and f'<option value="{mid}" selected>' in page
    r = c.post("/regeln/neu", data={"csrf_token": c.csrf, "name": "Redtronic", "manufacturer_id": str(mid),
                                    "start_price": "EK", "rounding_mode": "HALF_UP", "rounding_places": "2",
                                    "rounding_timing": "STEP", "step_1_type": "multiply", "step_1_value": "2,6",
                                    "zurueck": next_url}, follow_redirects=False)
    assert r.headers["location"] == next_url  # zurück zur Kalkulation
    page = c.get(next_url).text
    rule_id = re.search(r'<option value="(\d+)" selected>Redtronic', page).group(1)  # automatisch Standardregel

    # Schritt 6
    r = c.post(next_url, data={"csrf_token": c.csrf, "rule_id": rule_id, "quantity": "1"}, follow_redirects=False)
    page = c.get(r.headers["location"]).text
    assert 'class="current"><span>4</span>' in page
    assert "RT100" in page and "26,00" in page and "6,50" in page
    assert "Excel-Export" in page and "Mit Vorgängerliste vergleichen" in page


def test_open_redirect_blocked(admin_client):
    page = admin_client.get("/regeln/neu?zurueck=https://boese.example").text
    assert 'name="zurueck"' not in page
