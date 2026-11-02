"""Wörterbuch für den Datenblatt-Import: Wirkung im Import, nur Admin, pro Hersteller, Hersteller-Erkennung."""

import re

from backend.database.engine import session_scope
from backend.models.entities import DatasheetTerm, Manufacturer
from backend.services import datasheet_import as dsi
from backend.services import datasheet_terms
from backend.services import datasheets as ds
from tests.conftest import run_jobs
from tests.pdf_factory import make_pdf

PAGE = [(50, 790, 20, "FLASH UNIT"), (50, 770, 14, "Series Nova"),
        (50, 745, 10, "The Nova flash unit is built for the toughest sites and with the brightest output."),
        (50, 715, 12, "TECHNICAL DATA"),
        (50, 700, 10, "Lumen output"), (250, 700, 10, "900 lm"),
        (50, 688, 10, "Bracket"), (250, 688, 10, "Swivel bracket"),
        (50, 676, 10, "Strobe mode"), (250, 676, 10, "Quad burst"),
        (50, 650, 12, "ORDERING INFORMATION"),
        (50, 635, 10, "NV-100"), (250, 635, 10, "Swivel bracket, amber"),
        (50, 40, 8, "Novalux GmbH, www.novalux.example")]


def test_own_terms_win_in_import(settings):
    terms = {"MERKMAL": {"lumen output": "Lichtleistung", "bracket": "Montage", "strobe mode": "Blitzmuster"},
             "WERT": {"swivel bracket": "Schwenkhalter", "quad burst": "Vierfachblitz"},
             "PRODUKTART": {"flash unit": "Blitzleuchte"}}
    r = dsi.build(make_pdf([PAGE]), settings, 21, terms=terms)
    c = r.content
    assert c["kopf"] == {"titel": "LED Blitzleuchten", "untertitel": "Serie Nova"}
    props = {p["name"]: p["wert"] for p in c["eigenschaften"] if p["name"]}
    assert props["Lichtleistung"] == "900lm" and props["Montage"] == "Schwenkhalter"
    assert {"merkmal": "Blitzmuster", "wert": "Vierfachblitz"} in c["spez"]["zeilen"]
    rows = [r_["beschreibung"] for t in ds.tables(c) for r_ in t["zeilen"]]
    assert rows == ["LED Blitzleuchte, Schwenkhalter, gelb"]
    assert r.unknown == []
    # ohne Wörterbuch: unbekannte Begriffe für den Prüfbericht
    plain = dsi.build(make_pdf([PAGE]), settings, 22)
    assert {"art": "MERKMAL", "begriff": "Bracket"} in plain.unknown
    assert {"art": "WERT", "begriff": "Quad burst"} in plain.unknown


def test_manufacturer_entries_override_global_and_stay_with_manufacturer(app):
    with session_scope() as db:
        db.add_all([DatasheetTerm(kind="WERT", source="clear", target="klar", manufacturer=""),
                    DatasheetTerm(kind="WERT", source="clear", target="transparent", manufacturer="Novalux"),
                    DatasheetTerm(kind="WERT", source="mag", target="Magnetfuß", manufacturer="Andere")])
    with session_scope() as db:
        assert datasheet_terms.load(db, "novalux")["WERT"] == {"clear": "transparent"}
        assert datasheet_terms.load(db, None)["WERT"] == {"clear": "klar"}


def test_terms_page_admin_only_add_edit_delete(admin_client, user_client):
    assert user_client.get("/datenblatt/woerterbuch").status_code == 403
    assert "/datenblatt/woerterbuch" not in user_client.get("/datenblatt").text
    c = admin_client
    assert "/datenblatt/woerterbuch" in c.get("/datenblatt").text
    page = c.get("/datenblatt/woerterbuch?art=WERT&begriff=Quad+burst&hersteller=Novalux").text
    assert 'value="Quad burst"' in page and '<option value="WERT" selected>' in page
    c.post("/datenblatt/woerterbuch", data={"csrf_token": c.csrf, "art": "WERT", "begriff": "Quad  Burst:",
                                            "ziel": "Vierfachblitz", "hersteller": "Novalux"})
    with session_scope() as db:
        row = db.query(DatasheetTerm).one()
        assert (row.source, row.target, row.manufacturer) == ("quad burst", "Vierfachblitz", "Novalux")
        tid = row.id
    page = c.get("/datenblatt/woerterbuch").text
    assert "quad burst" in page and "Novalux" in page and "Eingebaute Regeln" in page
    c.post(f"/datenblatt/woerterbuch/{tid}/aendern", data={"csrf_token": c.csrf, "ziel": "4-fach-Blitz"})
    with session_scope() as db:
        assert db.get(DatasheetTerm, tid).target == "4-fach-Blitz"
    assert user_client.post(f"/datenblatt/woerterbuch/{tid}/loeschen",
                            data={"csrf_token": user_client.csrf}).status_code == 403
    c.post(f"/datenblatt/woerterbuch/{tid}/loeschen", data={"csrf_token": c.csrf})
    with session_scope() as db:
        assert db.query(DatasheetTerm).count() == 0


def test_upload_detects_manufacturer_and_uses_its_terms(admin_client, app):
    c = admin_client
    with session_scope() as db:
        db.add(Manufacturer(owner_id=1, name="Novalux", code="NX", aliases=[]))
        db.add(DatasheetTerm(kind="WERT", source="quad burst", target="Vierfachblitz", manufacturer="Novalux"))
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf},
               files={"datei": ("n.pdf", make_pdf([PAGE]), "application/pdf")}, follow_redirects=False)
    run_jobs(app)
    target = re.search(r'content="0;url=([^"]+)"', c.get(r.headers["location"]).text).group(1)
    editor = c.get(target).text
    assert "Hersteller im PDF erkannt: Novalux" in editor
    assert "Vierfachblitz" in editor and "NXNV-100" in editor
    assert "ins Wörterbuch" in editor and "begriff=Bracket" in editor and "hersteller=Novalux" in editor


def test_detect_manufacturer_needs_whole_word():
    a, b = Manufacturer(name="ECCO", aliases=[]), Manufacturer(name="Strands", aliases=["Strands Lighting"])
    assert datasheet_terms.detect_manufacturer("ECCO SAFETY GROUP, www.eccoesg.com ECCO", [a, b]) is a
    assert datasheet_terms.detect_manufacturer("ecconomy strandsX", [a, b]) is None
