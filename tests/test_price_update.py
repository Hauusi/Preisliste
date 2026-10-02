import io
import re
from decimal import Decimal

import openpyxl
from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import PriceUpdate, PriceUpdateItem
from tests.conftest import make_xlsx, run_jobs
from tests.test_import_web import upload

D = Decimal


def _import(c, app, tmp_path, name, rows, mid):
    list_id = int(upload(c, make_xlsx(tmp_path / f"{name}.xlsx", rows)).headers["location"].rsplit("/", 1)[1])
    r = c.post(f"/import/{list_id}/confirm", data={
        "csrf_token": c.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "description", "col_2": "supplier_price", "sep_2": ",", "manufacturer_id": str(mid),
        "currency": "EUR"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    run_jobs(app)
    return list_id


def test_new_price_list_only_our_articles(admin_client, tmp_path, app):
    c = admin_client
    c.post("/hersteller", data={"csrf_token": c.csrf, "name": "RaphiLED", "code": "RA"})
    with session_scope() as db:
        from backend.models.entities import Manufacturer
        mid = db.scalar(select(Manufacturer)).id
    r = c.post("/regeln/neu", data={"csrf_token": c.csrf, "name": "RaphiLED", "manufacturer_id": str(mid),
                                    "start_price": "EK", "rounding_mode": "HALF_UP", "rounding_places": "2",
                                    "rounding_timing": "STEP", "step_1_type": "multiply", "step_1_value": "2,6"},
               follow_redirects=False)
    rule_id = r.headers["location"].rsplit("/", 1)[1]
    ours = _import(c, app, tmp_path, "unsere_2025", [["Artikelnummer", "Bezeichnung", "EK"],
                                                    ["LED1", "Blitzmodul 1", "23,00"], ["LED2", "Blitzmodul 2", "26,70"],
                                                    ["BLITZ1", "Leuchte 1", "200,00"]], mid)
    rrp = _import(c, app, tmp_path, "hersteller_2026", [["Artikelnummer", "Bezeichnung", "EK"],
                                                       ["LED1", "Blitzmodul 1", "25,10"], ["BLITZ1", "Leuchte 1", "200,00"],
                                                       ["NEU9", "Neuheit", "99,00"]], mid)

    # Schritt 5 der Herstellerliste bietet die Option an, unsere Liste und die Regel sind vorausgewählt
    page = c.get(f"/listen/{rrp}/kalkulation").text
    assert "neue Preisliste nur mit unseren Artikeln" in page
    assert re.search(rf'<option value="{ours}" selected>', page)
    assert '<option value="EK" selected>' in page

    r = c.post("/aktualisierungen", data={"csrf_token": c.csrf, "base_id": ours, "source_id": rrp,
                                          "price_type": "EK", "rule_id": rule_id, "quantity": "1"},
               follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    with session_scope() as db:
        upd = db.scalar(select(PriceUpdate))
        items = {i.article_number: i for i in db.scalars(select(PriceUpdateItem))}
        summary = upd.summary
    assert set(items) == {"LED1", "LED2", "BLITZ1"}  # NEU9 ignoriert
    assert summary["ignoriert_nur_beim_hersteller"] == 1
    led1 = items["LED1"]
    assert (led1.status, led1.old_amount, led1.new_amount, led1.calculated_amount) == \
        ("AKTUALISIERT", D("23.00"), D("25.10"), D("65.26"))
    assert items["BLITZ1"].status == "UNVERAENDERT" and items["BLITZ1"].calculated_amount == D("520.00")
    led2 = items["LED2"]
    assert led2.status == "NICHT_IN_HERSTELLERLISTE" and led2.new_amount is None
    assert led2.calculated_amount == D("69.42")  # alter Preis 26,70 × 2,6, markiert

    page = c.get(url).text
    assert 'class="current"><span>6</span>' in page and "RALED1" in page and "65,26" in page

    wb = openpyxl.load_workbook(io.BytesIO(c.get(url + "/export").content))
    assert wb.sheetnames == ["Zusammenfassung", "Neue Preisliste", "Zu prüfen"]
    rows = {r[0]: r for r in wb["Neue Preisliste"].iter_rows(min_row=2, values_only=True)}
    assert set(rows) == {"RALED1", "RALED2", "RABLITZ1"}
    assert rows["RALED1"][5] == 25.1 and rows["RALED1"][6] == 65.26
    assert [r[0] for r in wb["Zu prüfen"].iter_rows(min_row=2, values_only=True)] == ["RALED2"]


def test_unclear_match_keeps_old_price(admin_client, tmp_path, app):
    c = admin_client
    c.post("/hersteller", data={"csrf_token": c.csrf, "name": "X"})
    with session_scope() as db:
        from backend.models.entities import Manufacturer
        mid = db.scalar(select(Manufacturer)).id
    ours = _import(c, app, tmp_path, "a", [["Art", "Bez", "EK"], ["ABC-1000", "Spezialteil Typ X", "5,00"]], mid)
    new = _import(c, app, tmp_path, "b", [["Art", "Bez", "EK"], ["ABC-1001", "Spezialteil Typ X", "6,00"]], mid)
    c.post("/aktualisierungen", data={"csrf_token": c.csrf, "base_id": ours, "source_id": new, "price_type": "EK"})
    with session_scope() as db:
        item = db.scalar(select(PriceUpdateItem))
    assert item.status == "NICHT_EINDEUTIG" and item.new_amount is None and "ABC-1001" in item.note


def test_update_form_errors(admin_client):
    r = admin_client.post("/aktualisierungen", data={"csrf_token": admin_client.csrf, "price_type": "EK"})
    assert r.status_code == 400 and "Herstellerliste wählen" in r.text
