"""Design-Vorlagen: fertiges B&B-Blatt gibt beim Import Aufbau, Reihenfolge und Textstil vor – nie Inhalte."""

import json
import re

from backend.ai.provider import MockProvider, set_provider
from backend.database.engine import session_scope
from backend.models.entities import Datasheet
from backend.services import datasheet_import as dsi
from backend.services import datasheet_templates as dst
from backend.services import datasheets as ds
from tests.conftest import run_jobs
from tests.test_datasheet_import import _pdf


def _template() -> dict:
    c = ds.empty_content()
    c["kopf"] = {"titel": "LED Blitzleuchten", "untertitel": "Serie 400"}
    c["einleitung"] = "Die Blitzleuchten der Serie 400 bieten eine Doppelblitz Funktion. Erhältlich in 3 Montageversionen."
    c["eigenschaften"] = [{"name": "Montage", "wert": "Fixmontage", "sichtbar": True},
                          {"name": "Spannungsbereich", "wert": "10-30V", "sichtbar": True},
                          {"name": "Wasserdicht", "wert": "IP67", "sichtbar": True},
                          {"name": "", "wert": "3 Jahre Garantie", "sichtbar": True}]
    c["spez"]["zeilen"] = [{"merkmal": "Blitzmuster", "wert": "Doppelblitz"}, {"merkmal": "Leistung", "wert": "8W"},
                           {"merkmal": "Gewicht", "wert": "1kg"}, {"merkmal": "Kabellänge", "wert": "4m"}]
    table = ds.new_table()
    table.update(zusatz="Serie 400", zeilenbilder="gross", bild_pos="oben", neue_seite=True,
                 zeilen=[{"bild": None, "artnr": "VAV11050", "farbe": "gelb", "beschreibung": "LED Blitzleuchte", "werte": []}])
    c["bloecke"] = [{"typ": "intro", "neue_seite": False, "sichtbar": True}, table,
                    {"typ": "spez", "neue_seite": False, "sichtbar": True},
                    {"typ": "anwendung", "neue_seite": False, "sichtbar": True}]
    return c


def test_apply_takes_order_and_layout_but_no_content():
    c = ds.empty_content()
    c["kopf"] = {"titel": "LED Blitzleuchten", "untertitel": "Serie Nova"}
    c["eigenschaften"] = [{"name": "Spannungsbereich", "wert": "12-24V", "sichtbar": True},
                          {"name": "Gehäuse", "wert": "Kunststoff", "sichtbar": True},
                          {"name": "", "wert": "Synchronisierbar", "sichtbar": True}]
    c["spez"]["zeilen"] = [{"merkmal": "Gewicht", "wert": "0.4kg"}, {"merkmal": "Leistung", "wert": "5W"}]
    table = ds.new_table()
    table["zeilen"] = [{"bild": None, "artnr": "NV-1", "farbe": "", "beschreibung": "LED Blitzleuchte", "werte": []}]
    c["bloecke"].append(table)
    out = dst.apply(c, _template())
    assert [(p["name"], p["wert"], p["sichtbar"]) for p in out["eigenschaften"]] == [
        ("Montage", "", True), ("Spannungsbereich", "12-24V", True), ("Wasserdicht", "", True),
        ("Gehäuse", "Kunststoff", True),
        ("", "3 Jahre Garantie", False),  # Vorschlag aus der Vorlage, ausgeblendet
        ("", "Synchronisierbar", True)]
    assert [z["merkmal"] for z in out["spez"]["zeilen"]] == ["Leistung", "Gewicht"]
    assert [b["typ"] for b in out["bloecke"]] == ["intro", "tabelle", "spez", "anwendung"]
    t = out["bloecke"][1]
    assert (t["zeilenbilder"], t["bild_pos"], t["neue_seite"], t["zusatz"]) == ("gross", "oben", True, "Serie Nova")
    assert [r["artnr"] for r in t["zeilen"]] == ["NV-1"]  # keine Artikel der Vorlage
    assert "1kg" not in json.dumps(out) and "VAV11050" not in json.dumps(out)


def test_choose_by_product_type():
    a = {"titel": "A", "art": "Scheinwerfer, Arbeitsscheinwerfer", "content": {}, "geaendert": "2026-01-01"}
    b = {"titel": "B", "art": "Arbeitsscheinwerfer", "content": {}, "geaendert": "2026-02-01"}
    assert dst.choose([a, b], "Arbeitsscheinwerfer") is b
    assert dst.choose([a, b], "scheinwerfer") is a
    assert dst.choose([a, b], "Blitzleuchte") is None and dst.choose([a, b], None) is None


def test_build_uses_template_for_spec_rows_and_ai_style(settings):
    tpl = {"titel": "LED Blitzleuchten – Serie 400", "art": "Blitzleuchte", "content": _template(), "geaendert": "x"}
    good = json.dumps({"beschreibung": "Robuste Blitzleuchte für Baufahrzeuge.", "punkte": []})
    ai = MockProvider(settings, [good])
    set_provider(ai)
    try:
        r = dsi.build(_pdf(), settings, 31, ai=ai, templates=[tpl])
    finally:
        set_provider(None)
    assert any("Design-Vorlage „LED Blitzleuchten – Serie 400“ verwendet" in x for x in r.report)
    assert "Stilvorlage" in ai.prompts[-1] and "Doppelblitz Funktion" in ai.prompts[-1]
    assert r.content["eigenschaften"][0]["name"] == "Montage"
    assert r.stats["produktart"] == "Blitzleuchte"
    # ohne passende Vorlage: unverändert
    other = dict(tpl, art="Arbeitsscheinwerfer")
    r2 = dsi.build(_pdf(), settings, 32, templates=[other])
    assert not any("Design-Vorlage" in x for x in r2.report)


def test_template_upload_and_marking_admin_only(admin_client, user_client, app):
    c = admin_client
    page = c.get("/datenblatt").text
    assert 'id="vorlagen"' in page and 'id="vorlagen"' not in user_client.get("/datenblatt").text
    c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf, "vorlage": "1"},
           files={"datei": ("bb.pdf", _pdf(), "application/pdf")})
    run_jobs(app)
    with session_scope() as db:
        sheet = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        assert sheet.is_template and sheet.template_kind == "Blitzleuchte"
        tid = sheet.id
    # normaler Benutzer: Vorlage-Schalter wird ignoriert bzw. verboten
    user_client.post("/datenblatt/aus-pdf", data={"csrf_token": user_client.csrf, "vorlage": "1"},
                     files={"datei": ("h.pdf", _pdf(), "application/pdf")})
    run_jobs(app)
    with session_scope() as db:
        mine = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        assert not mine.is_template
        assert mine.content["eigenschaften"]  # Import eines Benutzers nutzt die Vorlage des Admins
    assert user_client.post(f"/datenblatt/{tid}/vorlage", data={"csrf_token": user_client.csrf}).status_code in (403, 404)
    c.post(f"/datenblatt/{tid}/vorlage", data={"csrf_token": c.csrf, "aktiv": "1", "art": "Blitzleuchte, Blitzmodul"})
    with session_scope() as db:
        assert db.get(Datasheet, tid).template_kind == "Blitzleuchte, Blitzmodul"
    assert "Blitzleuchte, Blitzmodul" in c.get("/datenblatt").text
    c.post(f"/datenblatt/{tid}/vorlage", data={"csrf_token": c.csrf})
    with session_scope() as db:
        assert not db.get(Datasheet, tid).is_template and db.get(Datasheet, tid).template_kind is None


def test_import_report_names_template(admin_client, app):
    c = admin_client
    with session_scope() as db:
        db.add(Datasheet(owner_id=1, title="Vorlage Blitz", content=_template(), is_template=True,
                         template_kind="Blitzleuchte"))
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf},
               files={"datei": ("h.pdf", _pdf(), "application/pdf")}, follow_redirects=False)
    run_jobs(app)
    target = re.search(r'content="0;url=([^"]+)"', c.get(r.headers["location"]).text).group(1)
    assert "Design-Vorlage „Vorlage Blitz“ verwendet" in c.get(target).text
