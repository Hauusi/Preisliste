import io
import re

import openpyxl
from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import Manufacturer
from tests.conftest import make_xlsx, run_jobs
from tests.test_group_b_web import RULE_FORM
from tests.test_import_web import upload


def _add(client, **data):
    return client.post("/hersteller", data={"csrf_token": client.csrf, **data}, follow_redirects=False)


def test_code_validation(admin_client):
    assert _add(admin_client, name="Redtronic", code="rt").status_code == 303
    with session_scope() as db:
        assert db.scalar(select(Manufacturer).where(Manufacturer.name == "Redtronic")).code == "RT"
    r = _add(admin_client, name="Andere", code="RT")
    assert r.status_code == 400 and "schon an Redtronic vergeben" in r.text
    r = _add(admin_client, name="Andere", code="R-T")
    assert r.status_code == 400 and "nur Buchstaben" in r.text
    assert _add(admin_client, name="Ohne Kürzel").status_code == 303


def _import_with_code(client, tmp_path, app):
    p = make_xlsx(tmp_path / "rt.xlsx", [["Art.-Nr.", "Bezeichnung", "Listenpreis"],
                                        ["12345", "Platine", "100,00"], ["99", "Kabel", "5,00"]])
    list_id = int(upload(client, p).headers["location"].rsplit("/", 1)[1])
    r = client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "description", "col_2": "list_price", "sep_2": ",", "new_manufacturer": "Redtronic",
        "new_manufacturer_code": "rt", "currency": "EUR"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    run_jobs(app)
    return list_id


def test_code_shown_searched_and_original_kept(admin_client, tmp_path, app):
    list_id = _import_with_code(admin_client, tmp_path, app)
    page = admin_client.get(f"/listen/{list_id}").text
    assert "RT12345" in page
    data = admin_client.get(f"/api/price-lists/{list_id}/articles?q=RT12345").json()
    assert [a["artikelnummer"] for a in data["artikel"]] == ["12345"]  # Original bleibt gespeichert
    assert data["artikel"][0]["artikelnummer_anzeige"] == "RT12345"
    assert admin_client.get(f"/api/price-lists/{list_id}/articles?q=12345").json()["gesamt"] == 1


def test_code_in_import_must_be_unique(admin_client, tmp_path):
    _add(admin_client, name="Redtronic", code="RT")
    p = make_xlsx(tmp_path / "x.xlsx", [["Art.-Nr.", "Listenpreis"], ["1", "1,00"]])
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    r = admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "list_price", "new_manufacturer": "Neu", "new_manufacturer_code": "RT", "currency": "EUR"})
    assert r.status_code == 400 and "schon an Redtronic vergeben" in r.text


def test_default_rule_preselected_and_export_with_code(admin_client, tmp_path, app):
    list_id = _import_with_code(admin_client, tmp_path, app)
    r = admin_client.post("/regeln/neu", data={**RULE_FORM, "csrf_token": admin_client.csrf}, follow_redirects=False)
    rule_id = int(r.headers["location"].rsplit("/", 1)[1])
    with session_scope() as db:
        m = db.scalar(select(Manufacturer).where(Manufacturer.name == "Redtronic"))
        mid = m.id
    r = _add(admin_client, id=str(mid), name="Redtronic", code="RT", default_rule_id=str(rule_id),
             ignore_leading_zeros="1")
    assert r.status_code == 303
    page = admin_client.get(f"/listen/{list_id}/kalkulation").text
    assert re.search(rf'<option value="{rule_id}" selected>', page)
    assert "Standardregel von Redtronic (RT)" in page
    r = admin_client.post(f"/listen/{list_id}/kalkulation", data={"csrf_token": admin_client.csrf,
                                                                  "rule_id": rule_id, "quantity": "1"},
                          follow_redirects=False)
    run_url = r.headers["location"]
    assert "RT12345" in admin_client.get(run_url).text
    wb = openpyxl.load_workbook(io.BytesIO(admin_client.get(run_url + "/export").content))
    rows = list(wb["Kalkulation"].iter_rows(min_row=3, values_only=True))
    assert ("RT12345", "12345") in [(r[1], r[2]) for r in rows]


def test_rule_form_shows_step_cards(admin_client):
    page = admin_client.get("/regeln/neu").text
    assert 'class="step "' in page and 'class="step spare"' in page
    assert "/static/rule_form.js" in page and "+ Schritt hinzufügen" in page
    # neue Feldnamen werden verarbeitet
    r = admin_client.post("/regeln/neu", data={
        "csrf_token": admin_client.csrf, "name": "Rundung", "start_price": "LISTE", "rounding_mode": "HALF_UP",
        "rounding_places": "2", "rounding_timing": "STEP",
        "step_1_type": "round", "step_1_value": "0,05", "step_1_mode": "UP",
        "step_2_type": "round_ending", "step_2_value": "0,90", "step_2_direction": "DOWN"}, follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].rsplit("/", 1)[1]
    page = admin_client.post(f"/regeln/{rid}/test", data={"csrf_token": admin_client.csrf, "amount": "12,34",
                                                          "quantity": "1"}).text
    assert "11,90" in page  # 12,34 -> 12,35 (auf 0,05 aufrunden) -> 11,90 (Endung ,90 abrunden)


def test_new_rule_form_defaults(admin_client):
    page = admin_client.get("/regeln/neu").text
    assert 'name="rounding_places" min="0" max="6" value="2"' in page


def test_rule_with_factor_and_clear_formula_error(admin_client):
    base = {"csrf_token": admin_client.csrf, "name": "RaphiLED", "start_price": "EK", "rounding_mode": "HALF_UP",
            "rounding_places": "2", "rounding_timing": "STEP"}
    r = admin_client.post("/regeln/neu", data={**base, "step_1_type": "formula", "step_1_value": "* 2,6"})
    assert r.status_code == 400
    assert "Value error" not in r.text and "current * 2,6" in r.text
    r = admin_client.post("/regeln/neu", data={**base, "step_1_type": "multiply", "step_1_value": "2,6"},
                          follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].rsplit("/", 1)[1]
    page = admin_client.post(f"/regeln/{rid}/test", data={"csrf_token": admin_client.csrf, "amount": "10,00",
                                                          "quantity": "1"}).text
    assert "26,00" in page
