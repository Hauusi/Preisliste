import re

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import Article, PriceList
from tests.conftest import make_xlsx


def upload(client, path, name=None):
    with open(path, "rb") as fh:
        return client.post("/import", data={"csrf_token": client.csrf},
                           files={"file": (name or path.name, fh, "application/octet-stream")},
                           follow_redirects=False)


def test_full_import_flow(admin_client, tmp_path):
    p = make_xlsx(tmp_path / "ACME_2026.xlsx", [
        ["ACME Preisliste 2026"], [],
        ["Art.-Nr.", "Bezeichnung", "EK netto", "UVP"],
        ["A-1", "<script>alert(1)</script>", "1.234,56", "2.000,00"],
        ["A-2", "Mutter", "0,20", "0,49"],
    ])
    r = upload(admin_client, p)
    assert r.status_code == 303
    list_id = int(r.headers["location"].rsplit("/", 1)[1])

    page = admin_client.get(f"/import/{list_id}").text
    assert "<script>alert(1)</script>" not in page  # Ausgabe wird escaped
    assert "&lt;script&gt;" in page
    assert re.search(r'name="col_0">.*?<option value="article_number" selected', page, re.S)
    assert 'name="header_row" value="3"' in page

    r = admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "3", "header_rows": "1",
        "col_0": "article_number", "col_1": "description", "col_2": "supplier_price", "col_3": "rrp",
        "sep_2": ",", "sep_3": ",", "new_manufacturer": "ACME", "currency": "EUR",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text
    page = admin_client.get(f"/listen/{list_id}").text
    assert "1.234,56" in page and "Mutter" in page

    data = admin_client.get(f"/api/price-lists/{list_id}/articles").json()
    assert data["gesamt"] == 2
    ek = [p for p in data["artikel"][0]["preise"] if p["typ"] == "EK"][0]
    assert ek == {"typ": "EK", "betrag": "1234.56", "waehrung": "EUR", "ab_menge": None}

    # Bereits importierte Liste kann nicht erneut bestätigt werden
    r = admin_client.post(f"/import/{list_id}/confirm", data={"csrf_token": admin_client.csrf})
    assert r.status_code == 409


def test_confirm_requires_mapping_and_manufacturer(admin_client, tmp_path):
    p = make_xlsx(tmp_path / "l.xlsx", [["Art.-Nr.", "EK"], ["A", "1,00"]])
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    r = admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
    })
    assert r.status_code == 400
    assert "Preisspalte" in r.text and "Hersteller" in r.text
    with session_scope() as db:
        assert db.get(PriceList, list_id).status == "ENTWURF"
        assert db.scalar(select(Article).where(Article.price_list_id == list_id)) is None


def test_upload_rejections(admin_client, tmp_path):
    p = make_xlsx(tmp_path / "l.xlsx", [["x"]])
    r = upload(admin_client, p, "liste.xlsm")
    assert r.status_code == 400 and "Makros" in r.text
    bad = tmp_path / "kaputt.xlsx"
    bad.write_bytes(b"kein excel")
    r = upload(admin_client, bad)
    assert r.status_code == 400 and "keine gültige" in r.text


def test_upload_size_limit(admin_client, tmp_path, settings):
    settings.max_upload_mb = 1
    big = tmp_path / "gross.xlsx"
    big.write_bytes(b"PK\x03\x04" + b"0" * (2 * 1024 * 1024))
    r = upload(admin_client, big)
    assert r.status_code == 400 and "größer als 1 MB" in r.text
    assert list(settings.upload_dir.iterdir()) == []  # nichts liegen geblieben


def test_discard_draft(admin_client, tmp_path, settings):
    p = make_xlsx(tmp_path / "l.xlsx", [["Art.-Nr.", "EK"], ["A", 1]])
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    admin_client.post(f"/import/{list_id}/verwerfen", data={"csrf_token": admin_client.csrf})
    assert list(settings.upload_dir.iterdir()) == []
    assert admin_client.get(f"/import/{list_id}").status_code == 404


def test_pagination_and_filter(admin_client, tmp_path):
    rows = [["Art.-Nr.", "EK"]] + [[f"N{i}", "1,00"] for i in range(120)] + [["BAD", "x"]]
    p = make_xlsx(tmp_path / "l.xlsx", rows)
    list_id = int(upload(admin_client, p).headers["location"].rsplit("/", 1)[1])
    admin_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": admin_client.csrf, "sheet": "Preise", "header_row": "1",
        "col_0": "article_number", "col_1": "supplier_price", "new_manufacturer": "X", "currency": "EUR",
    })
    data = admin_client.get(f"/api/price-lists/{list_id}/articles?page=3").json()
    assert data["seiten"] == 3 and data["gesamt"] == 121 and len(data["artikel"]) == 21
    data = admin_client.get(f"/api/price-lists/{list_id}/articles?status=FEHLER").json()
    assert [a["artikelnummer"] for a in data["artikel"]] == ["BAD"]
    page = admin_client.get(f"/listen/{list_id}/meldungen?level=FEHLER").text
    assert "KEIN_BETRAG" in page
