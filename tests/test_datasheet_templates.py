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


def test_template_library_admin_only_hidden_from_list(admin_client, user_client, app):
    c = admin_client
    assert user_client.get("/datenblatt/vorlagen").status_code == 403
    assert "/datenblatt/vorlagen" in c.get("/datenblatt").text
    assert "/datenblatt/vorlagen" not in user_client.get("/datenblatt").text
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf, "vorlage": "1"},
               files={"datei": ("bb.pdf", _pdf(), "application/pdf")}, follow_redirects=False)
    run_jobs(app)
    job_page = c.get(r.headers["location"]).text
    target = re.search(r'content="0;url=([^"]+)"', job_page).group(1)
    assert target.startswith("/datenblatt/vorlagen?job=")
    page = c.get(target).text
    assert "Vorlage gespeichert" in page and "Was diese Vorlage vorgibt" in page and "Spezifikation:" in page
    with session_scope() as db:
        sheet = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        assert sheet.is_template and sheet.template_kind == "Blitzleuchte"
        assert sheet.content["einleitung"].startswith("Die Blitzleuchte ist robust")  # unser Text wörtlich
        tid, title = sheet.id, sheet.title
    assert title not in c.get("/datenblatt").text  # nicht in der normalen Liste
    # normaler Benutzer: Vorlage-Schalter wird ignoriert; sein Import nutzt die Vorlage des Admins
    user_client.post("/datenblatt/aus-pdf", data={"csrf_token": user_client.csrf, "vorlage": "1"},
                     files={"datei": ("h.pdf", _pdf(), "application/pdf")})
    run_jobs(app)
    with session_scope() as db:
        mine = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        assert not mine.is_template
    assert user_client.post(f"/datenblatt/{tid}/vorlage", data={"csrf_token": user_client.csrf}).status_code in (403, 404)
    c.post(f"/datenblatt/{tid}/vorlage", data={"csrf_token": c.csrf, "aktiv": "1", "art": "Blitzleuchte, Blitzmodul"})
    with session_scope() as db:
        assert db.get(Datasheet, tid).template_kind == "Blitzleuchte, Blitzmodul"
    assert "Blitzleuchte, Blitzmodul" in c.get("/datenblatt/vorlagen").text
    c.post(f"/datenblatt/{tid}/vorlage", data={"csrf_token": c.csrf})
    with session_scope() as db:
        assert not db.get(Datasheet, tid).is_template and db.get(Datasheet, tid).template_kind is None


def test_template_with_manufacturer_sheet_suggests_words(admin_client, app):
    from backend.models.entities import DatasheetTerm
    from tests.pdf_factory import make_pdf

    ours = [(50, 780, 22, "LED ARBEITSSCHEINWERFER"), (50, 760, 12, "SERIE UNITY"),
            (50, 730, 10, "Die Scheinwerfer der Serie Unity bieten ein modernes und schlankes Design mit starker Ausleuchtung."),
            (50, 700, 12, "SPEZIFIKATIONEN"),
            (50, 680, 10, "Spannungsbereich:"), (300, 680, 10, "10-32V"),
            (50, 665, 10, "Montage:"), (300, 665, 10, "Schraubmontage (M8)"),
            (50, 650, 10, "Anschluss:"), (300, 650, 10, "Deutsch Stecker"),
            (50, 635, 10, "Linsenfarbe:"), (300, 635, 10, "klar")]
    theirs = [(50, 780, 22, "UNITY WORK LIGHT"),
              (50, 750, 10, "Become a professional with the Unity series and the strong light output for the job."),
              (50, 720, 12, "TECHNICAL DATA"),
              (50, 700, 10, "Voltage"), (250, 700, 10, "10-32 V"),
              (50, 685, 10, "Mounting"), (250, 685, 10, "Single screw (M8)"),
              (50, 670, 10, "Plug type"), (250, 670, 10, "DT-2PIN"),
              (50, 655, 10, "Color lens"), (250, 655, 10, "Clear")]
    c = admin_client
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf, "vorlage": "1", "art": "Arbeitsscheinwerfer"},
               files={"datei": ("bb.pdf", make_pdf([ours]), "application/pdf"),
                      "vergleich": ("h.pdf", make_pdf([theirs]), "application/pdf")}, follow_redirects=False)
    run_jobs(app)
    target = re.search(r'content="0;url=([^"]+)"', c.get(r.headers["location"]).text).group(1)
    page = c.get(target).text
    assert "Wortwahl aus dem Vergleich" in page
    pairs = re.findall(r'name="begriff_(\d+)" value="([^"]+)".*?name="ziel_\1" value="([^"]+)"', page, re.S)
    found = {(b, z) for _i, b, z in pairs}
    assert ("Single screw (M8)", "Schraubmontage (M8)") in found  # Wortlaut, gleiche Zahl
    assert ("Plug type", "Anschluss") in found  # Zeilenname über gleichen Wert („DT-2PIN“ = „Deutsch Stecker“)
    assert not any(b.startswith("10-32") for b, _z in found)  # Zahlen werden nicht gelernt
    i = next(i for i, b, _z in pairs if b == "Single screw (M8)")
    c.post("/datenblatt/woerterbuch/uebernehmen", data={"csrf_token": c.csrf, "wahl": [i], "hersteller": "",
                                                        f"art_{i}": "WERT", f"begriff_{i}": "Single screw (M8)",
                                                        f"ziel_{i}": "Schraubmontage (M8)"})
    with session_scope() as db:
        assert [(t.source, t.target) for t in db.query(DatasheetTerm)] == [("single screw (m8)", "Schraubmontage (M8)")]
        sheet = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        assert sheet.template_kind == "Arbeitsscheinwerfer"
        assert [z["merkmal"] for z in sheet.content["spez"]["zeilen"]] == ["Anschluss", "Linsenfarbe"]  # alle behalten


def test_apply_copies_image_layout_by_slot():
    tpl = _template()
    tpl["bilder_oben"] = ["a" * 16 + ".png"]
    tpl["zeichnungen"] = ["b" * 16 + ".jpg"]
    tpl["bild_groesse"] = {"a" * 16: 140, "b" * 16: 70}
    tpl["bild_versatz"] = {"a" * 16: [3.0, -2.0]}
    tpl["aufteilung"] = "bild"
    tpl["bloecke"][3]["sichtbar"] = False  # Anwendungsbilder aus
    c = ds.empty_content()
    c["bilder_oben"] = ["1" * 16 + ".png", "2" * 16 + ".png"]
    c["zeichnungen"] = ["3" * 16 + ".jpg"]
    out = dst.apply(c, tpl)
    assert out["bilder_oben"] == ["1" * 16 + ".png"]  # so viele Produktbilder wie die Vorlage
    assert out["bild_groesse"] == {"1" * 16: 140, "3" * 16: 70} and out["bild_versatz"] == {"1" * 16: [3.0, -2.0]}
    assert out["aufteilung"] == "bild"
    assert [b["sichtbar"] for b in out["bloecke"] if b["typ"] == "anwendung"] == [False]


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
