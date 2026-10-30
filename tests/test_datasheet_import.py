"""Datenblatt aus Hersteller-PDF: Erkennung von Titel, Text, Technischen Daten, Artikelnummern und Bildern,
Hintergrundjob, Bericht im Editor, lokale KI nur für den Beschreibungstext."""

import json
import re

from backend.ai.provider import MockProvider, set_provider
from backend.services import datasheet_import as dsi
from backend.services import datasheets as ds
from tests.conftest import run_jobs
from tests.pdf_factory import make_pdf

PAGE1 = [(50, 780, 22, "LED-BLITZLEUCHTE"), (50, 755, 12, "(Serie Test)"),
         (50, 700, 12, "ANWENDUNG"),
         (50, 680, 10, "Die Blitzleuchte ist robust und für den harten Einsatz auf Baufahrzeugen gebaut. Sie ist sehr"),
         (50, 666, 10, "hell und lässt sich einfach montieren, auch nachträglich an vorhandenen Halterungen."),
         (50, 630, 10, "•  5 Jahre Garantie"), (50, 616, 10, "•  Synchronisierbar")]
PAGE2 = [(50, 780, 12, "TECHNISCHE DATEN"), (250, 750, 10, "12 V DC"), (380, 750, 10, "24 V DC"),
         (50, 730, 10, "Spannungsbereich"), (250, 730, 10, "10 bis 15 V"), (380, 730, 10, "20 bis 30 V"),
         (50, 710, 10, "Schutzart"), (310, 710, 10, "IP 67"),
         (50, 690, 10, "Leistung"), (250, 690, 10, "ca. 5 W"), (380, 690, 10, "ca. 6 W"),
         (50, 670, 10, "Montage"), (310, 670, 10, "Schraubmontage"), (310, 658, 10, "Magnetfuß"),
         (50, 620, 12, "ARTIKELNUMMERN"),
         (50, 600, 10, "Typ rund"), (250, 600, 10, "12 V DC"), (380, 600, 10, "24 V DC"),
         (50, 580, 10, "LED gelb"), (250, 580, 10, "4711-A"), (380, 580, 10, "4711-B"),
         (50, 560, 10, "LED blau"), (310, 560, 10, "auf Anfrage"),
         (50, 540, 10, "Zubehör"),
         (50, 520, 10, "Magnetfuß"), (250, 520, 10, "900"), (380, 520, 10, "900")]


def _pdf():
    return make_pdf([PAGE1, PAGE2], image_on_page=0)


def test_build_fills_all_blocks(settings):
    r = dsi.build(_pdf(), settings, 1, code="BL", known_numbers={"4711A"})
    c = r.content
    assert c["kopf"] == {"titel": "LED-Blitzleuchte", "untertitel": "Serie Test"}
    assert c["einleitung"].startswith("Die Blitzleuchte ist robust") and "sehr hell" in c["einleitung"]
    props = {p["name"]: p["wert"] for p in c["eigenschaften"]}
    assert props["Spannung"] == "12 V DC: 10 bis 15 V\n24 V DC: 20 bis 30 V"  # je Spalte untereinander
    assert props["Schutzart"] == "IP 67" and props["Montage"] == "Schraubmontage\nMagnetfuß"  # Folgezeile
    assert [p["wert"] for p in c["eigenschaften"] if not p["name"]] == ["5 Jahre Garantie", "Synchronisierbar"]
    assert c["spez"]["zeilen"] == [{"merkmal": "Leistung", "wert": "12 V DC: ca. 5 W\n24 V DC: ca. 6 W"}]
    tables = [b for b in c["bloecke"] if b["typ"] == "tabelle"]
    assert [(t["titel"], t["zusatz"]) for t in tables] == [("Bestellinformationen", "Typ rund"), ("Zubehör", "")]
    rows = [(z["artnr"], z["beschreibung"], z["farbe"]) for z in tables[0]["zeilen"]]
    assert rows == [("BL4711-A", "LED gelb, 12 V DC", "gelb"), ("BL4711-B", "LED gelb, 24 V DC", "gelb")]  # ohne „auf Anfrage“
    assert [(z["artnr"], z["beschreibung"]) for z in tables[1]["zeilen"]] == [("BL900", "Magnetfuß")]  # gleiche Nr. einmal
    assert len(c["bilder_oben"]) == 1 and c["bilder_oben"][0].endswith(".png")  # freigestelltes Produktbild
    assert "1 von 3 Artikelnummern stehen in eurer aktuellen Preisliste des Herstellers." in r.report
    # Ergebnis ist gültiger Baukasten-Inhalt
    clean = ds.sanitize(c, ds.image_names(settings, 1))
    assert clean["bilder_oben"] == c["bilder_oben"] and len(ds.tables(clean)) == 2


def test_list_layout_with_multiline_descriptions():
    lines = ["          Artikel                         Beschreibung",
             "",
             "          VG100                    LED Rundumleuchte, gelb, Fixmontage",
             "",
             "                                    LED Rundumleuchte, gelb, Rohrmontage",
             "          VG200                    OE-Teile Nummer: 12345",
             "",
             "          VG300                    LED Rundumleuchte, blau"]
    groups = dsi.parse_articles(lines, "Funktion: Rotation")
    assert groups[0]["titel"] == "Funktion: Rotation"
    assert groups[0]["zeilen"] == [("VG100", "LED Rundumleuchte, gelb, Fixmontage"),
                                   ("VG200", "LED Rundumleuchte, gelb, Rohrmontage OE-Teile Nummer: 12345"),
                                   ("VG300", "LED Rundumleuchte, blau")]


def test_title_fallbacks():
    assert dsi._title(["Ein normaler Satz als erste Zeile.\nLED RUNDUMLEUCHTEN - SERIE ATLAS"]) == (
        "LED Rundumleuchten", "Serie Atlas")
    assert dsi._title(["kein titel hier."], "Rundumleuchte Atlas.indd") == ("Rundumleuchte Atlas", "")


def test_upload_runs_job_and_editor_shows_report(admin_client, app, settings):
    c = admin_client
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf},
               files={"datei": ("hersteller.pdf", _pdf(), "application/pdf")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/jobs/")
    job_url = r.headers["location"]
    run_jobs(app)
    page = c.get(job_url).text
    target = re.search(r'http-equiv="refresh" content="0;url=([^"]+)"', page).group(1)  # automatisch weiter
    assert re.fullmatch(r"/datenblatt/\d+\?import=\d+", target)
    sid = int(target.split("/")[2].split("?")[0])
    editor = c.get(target).text
    assert "Aus dem Herstellerblatt erstellt" in editor and "als gekürzter Originaltext" in editor
    assert "LED-Blitzleuchte" in editor and "BL4711" not in editor and "4711-A" in editor
    assert "Aus dem Herstellerblatt" not in c.get(f"/datenblatt/{sid}").text  # Bericht nur direkt danach
    assert not (ds.image_dir(settings, sid) / "hersteller.pdf").exists()  # PDF wird nicht aufbewahrt


def test_upload_with_manufacturer_prefixes_code(admin_client, app):
    from tests.test_price_update import _ours, _setup

    c = admin_client
    mid, _rule = _setup(c)
    page = c.get("/datenblatt").text
    assert f'<option value="{mid}">' in page
    c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf, "hersteller": str(mid)},
           files={"datei": ("h.pdf", _pdf(), "application/pdf")})
    run_jobs(app)
    from backend.database.engine import session_scope
    from backend.models.entities import Datasheet, Manufacturer

    with session_scope() as db:
        code = db.get(Manufacturer, mid).code
        sheet = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        nrs = [z["artnr"] for t in ds.tables(sheet.content) for z in t["zeilen"]]
    assert nrs[0] == f"{code}4711-A"


def test_rejects_non_pdf_and_text_less_pdf(admin_client, app, settings):
    c = admin_client
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf},
               files={"datei": ("x.pdf", b"<html>nope</html>", "application/pdf")})
    assert "kein PDF" in r.text
    try:
        dsi.build(make_pdf([[]]), settings, 5)
        raise AssertionError("ohne Text muss abgebrochen werden")
    except dsi.PdfError as exc:
        assert "kein lesbarer Text" in str(exc)
    assert c.post("/datenblatt/aus-pdf", data={}, files={"datei": ("h.pdf", _pdf(), "application/pdf")}).status_code in (400, 403)


def test_local_ai_writes_description_but_never_invents_numbers(settings):
    good = json.dumps({"beschreibung": "Robuste Blitzleuchte für Baufahrzeuge. Sehr hell und einfach zu montieren.",
                       "punkte": ["Einfache Montage"]})
    invented = json.dumps({"beschreibung": "Robuste Blitzleuchte mit 9000 Lumen für Baufahrzeuge.", "punkte": []})
    ai = MockProvider(settings, [invented, invented, invented, good])
    set_provider(ai)
    try:
        r = dsi.build(_pdf(), settings, 2, ai=ai)
        # erfundene Zahl -> verworfen (3 Versuche), danach Originaltext
        assert r.content["einleitung"].startswith("Die Blitzleuchte ist robust")
        assert any("KI nicht verwendet" in x for x in r.report)
        r = dsi.build(_pdf(), settings, 3, ai=ai)
        assert r.content["einleitung"] == "Robuste Blitzleuchte für Baufahrzeuge. Sehr hell und einfach zu montieren."
        # Aufzählung aus der Datei hat Vorrang vor KI-Stichpunkten
        assert [p["wert"] for p in r.content["eigenschaften"] if not p["name"]] == ["5 Jahre Garantie", "Synchronisierbar"]
        assert "Die Blitzleuchte ist robust" in ai.prompts[-1]
    finally:
        set_provider(None)
