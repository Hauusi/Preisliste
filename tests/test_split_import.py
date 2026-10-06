from decimal import Decimal

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import Comparison, ComparisonItem, Job, PriceList
from tests.conftest import make_xlsx, run_jobs
from tests.test_import_web import upload

ROWS = [
    ["Artikelnummer", "Artikeltext", "Preis RRP 2025", "Preis RRP 2026"],
    ["RALED1", "Blitzmodul LED 1", 23, 25.1],
    ["RALED2", "Blitzmodul LED 2", 26.7, 28.5],
    ["RABLITZ1", "Blitzleuchte BLITZ 1", 200, 200],
    ["RABLITZ2", "Blitzleuchte BLITZ 2", 240.14, 230],
]


def _setup(client):
    r = client.post("/hersteller", data={"csrf_token": client.csrf, "name": "RaphiLED", "code": "RA"},
                    follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as db:
        from backend.models.entities import Manufacturer
        return db.scalar(select(Manufacturer).where(Manufacturer.name == "RaphiLED")).id


def test_two_year_columns_split_into_two_lists_and_compare(admin_client, tmp_path, app):
    mid = _setup(admin_client)
    p = make_xlsx(tmp_path / "RAPREISLISTE.xlsx", ROWS)
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    # Schritt 2 -> 3, Hersteller über das Kürzel der Artikelnummern vorgeschlagen
    r = admin_client.post(f"/import/{list_id}/spalten", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "header_rows": "1",
        "col_0": "article_number", "col_1": "description", "col_2": "supplier_price", "col_3": "supplier_price"},
        follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/import/{list_id}"
    page = admin_client.get(r.headers["location"]).text
    assert f'<option value="{mid}" selected>RaphiLED (RA)</option>' in page
    assert "in zwei Listen aufgeteilt" in page
    assert 'name="strip_code" value="1" checked' in page  # Datei enthält das Kürzel schon
    # Beide Spalten als EK, rechte Spalte zuerst im Formular -> Reihenfolge kommt aus den Jahren
    r = admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "header_rows": "1",
        "col_0": "article_number", "col_1": "description", "col_3": "supplier_price", "col_2": "supplier_price",
        "manufacturer_id": str(mid), "currency": "EUR", "strip_code": "1"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    run_jobs(app)
    job_page = admin_client.get(r.headers["location"]).text
    assert "Datei in zwei Listen aufgeteilt" in job_page and "Vergleich alt/neu ansehen" in job_page
    assert "Weiter: Kalkulieren" in job_page
    with session_scope() as db:
        job = db.scalar(select(Job).order_by(Job.id.desc()))
        assert job.status == "FERTIG", job.message
        old_id, new_id = job.result["price_list_ids"]
        assert db.get(PriceList, old_id).name == "RAPREISLISTE – Preis RRP 2025"
        assert db.get(PriceList, new_id).name == "RAPREISLISTE – Preis RRP 2026"
        cmp = db.get(Comparison, job.result["comparison_id"])
        assert (cmp.old_price_list_id, cmp.new_price_list_id, cmp.price_type) == (old_id, new_id, "EK")
        items = {i.article_number: i for i in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp.id))}
    # Kürzel wurde beim Import abgeschnitten: gespeichert LED1, angezeigt RALED1
    assert items["LED1"].status == "PREIS_ERHOEHT" and items["LED1"].difference == Decimal("2.1")
    assert items["BLITZ1"].status == "UNVERAENDERT"
    assert items["BLITZ2"].status == "PREIS_GESENKT"
    page = admin_client.get(f"/vergleiche/{cmp.id}").text
    assert "RALED1" in page and "RARALED1" not in page


def test_left_column_is_old_without_years(admin_client, tmp_path, app):
    mid = _setup(admin_client)
    rows = [["Art.-Nr.", "EK alt", "EK neu"], ["RA1", 1, 2]]
    list_id = int(upload(admin_client, make_xlsx(tmp_path / "x.xlsx", rows)).headers["location"].rsplit("/", 1)[1])
    admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "supplier_price", "col_2": "supplier_price", "manufacturer_id": str(mid), "currency": "EUR"})
    run_jobs(app)
    with session_scope() as db:
        job = db.scalar(select(Job).order_by(Job.id.desc()))
        assert job.result["labels"] == ["EK alt", "EK neu"]


def test_split_limits(admin_client, tmp_path):
    mid = _setup(admin_client)
    rows = [["Art.-Nr.", "A", "B", "C"], ["RA1", 1, 2, 3]]
    list_id = int(upload(admin_client, make_xlsx(tmp_path / "x.xlsx", rows)).headers["location"].rsplit("/", 1)[1])
    base = {"csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
            "manufacturer_id": str(mid), "currency": "EUR"}
    r = admin_client.post(f"/import/{list_id}/confirm", data={**base, "col_1": "supplier_price",
                                                              "col_2": "supplier_price", "col_3": "supplier_price"})
    assert r.status_code == 400 and "höchstens zwei" in r.text
    r = admin_client.post(f"/import/{list_id}/confirm", data={**base, "col_1": "supplier_price",
                                                              "col_2": "supplier_price", "col_3": "article_number"})
    assert r.status_code == 400 and "Artikelnummer ist mehreren Spalten zugeordnet" in r.text


def test_supplier_numbers_get_prefix_and_strip_warns(admin_client, tmp_path, app):
    mid = _setup(admin_client)
    rows = [["Artikelnummer", "EK"], ["LED1", "10,00"], ["RAD5", "1,00"]]
    list_id = int(upload(admin_client, make_xlsx(tmp_path / "led.xlsx", rows)).headers["location"].rsplit("/", 1)[1])
    base = {"csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
            "col_1": "supplier_price", "sep_1": ",", "manufacturer_id": str(mid), "currency": "EUR"}
    admin_client.post(f"/import/{list_id}/confirm", data=base)
    run_jobs(app)
    data = admin_client.get(f"/api/price-lists/{list_id}/articles").json()
    shown = {a["artikelnummer"]: a["artikelnummer_anzeige"] for a in data["artikel"]}
    assert shown == {"LED1": "RALED1", "RAD5": "RARAD5"}  # immer Kürzel davor, auch wenn die Nummer mit RA beginnt


def test_strip_code_requires_code(admin_client, tmp_path):
    admin_client.post("/hersteller", data={"csrf_token": admin_client.csrf, "name": "OhneKuerzel"})
    with session_scope() as db:
        from backend.models.entities import Manufacturer
        mid = db.scalar(select(Manufacturer)).id
    rows = [["Artikelnummer", "EK"], ["X1", "1,00"]]
    list_id = int(upload(admin_client, make_xlsx(tmp_path / "x.xlsx", rows)).headers["location"].rsplit("/", 1)[1])
    r = admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "supplier_price", "manufacturer_id": str(mid), "currency": "EUR", "strip_code": "1"})
    assert r.status_code == 400 and "kein Kürzel" in r.text
