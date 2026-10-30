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
    # B&B-Begriffe in B&B-Reihenfolge
    assert [p["name"] for p in c["eigenschaften"] if p["name"]] == [
        "Spannungsbereich", "Wasserdicht", "Montage", "Zulassungen", "Gehäuse", "Abmessungen"]
    assert props["Spannungsbereich"] == "12V: 10 bis 15V\n24V: 20 bis 30V"  # je Spalte untereinander, B&B-Schreibweise
    assert props["Wasserdicht"] == "IP67" and props["Montage"] == "Schraubmontage\nMagnetfuß"  # Folgezeile
    assert [p["wert"] for p in c["eigenschaften"] if not p["name"]] == ["5 Jahre Garantie", "Synchronisierbar"]
    assert c["spez"]["zeilen"] == [{"merkmal": "Leistung", "wert": "12V DC: ca. 5W\n24V DC: ca. 6W"}]
    tables = [b for b in c["bloecke"] if b["typ"] == "tabelle"]
    assert [(t["titel"], t["zusatz"]) for t in tables] == [("Bestellinformationen", "Typ rund"), ("Zubehör", "")]
    rows = [(z["artnr"], z["beschreibung"], z["farbe"]) for z in tables[0]["zeilen"]]
    assert rows == [("BL4711-A", "LED-Blitzleuchte, gelb, 12 V DC", "gelb"),  # Artikelart vorne, ohne „auf Anfrage“
                    ("BL4711-B", "LED-Blitzleuchte, gelb, 24 V DC", "gelb")]
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
    assert groups[0]["zeilen"] == [("VG100", "LED Rundumleuchte, gelb, Fixmontage", []),
                                   ("VG200", "LED Rundumleuchte, gelb, Rohrmontage OE-Teile Nummer: 12345", []),
                                   ("VG300", "LED Rundumleuchte, blau", [])]


def test_list_with_extra_columns():
    lines = ["     Artikel            Beschreibung                          Zulassung          Montage",
             "     RTG3HSA0CB         LED Blitzmodul Gecko 3, 11-30V, gelb  ECE-R65 Klasse I   Horizontal",
             "     RTG3HSB0CB         LED Blitzmodul Gecko 3, 11-30V, blau  ECE-R65 Klasse I   Horizontal"]
    g = dsi.parse_articles(lines, "GECKO 3 - HORIZONTALE MONTAGE")[0]
    assert g["spalten"] == ["Zulassung", "Montage"]
    assert g["zeilen"][0] == ("RTG3HSA0CB", "LED Blitzmodul Gecko 3, 11-30V, gelb", ["ECE-R65 Klasse I", "Horizontal"])


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


def test_product_type_in_description():
    assert dsi.with_product_type("LED-Lichtsignalgeber", "LED rot, 12 V DC") == "LED-Lichtsignalgeber, rot, 12 V DC"
    assert dsi.with_product_type("LED Rundumleuchten", "LED Rundumleuchte, Rotation, gelb") == "LED Rundumleuchte, Rotation, gelb"
    assert dsi.with_product_type("Arbeitsscheinwerfer", "rund, 1200 lm") == "Arbeitsscheinwerfer, rund, 1200 lm"
    assert dsi.with_product_type("", "LED rot") == "LED rot"


def test_bb_terms_warranty_bullet_and_multicolor(settings):
    page = [(50, 780, 22, "LED-LEUCHTBALKEN"),
            (50, 740, 12, "TECHNISCHE DATEN"),
            (50, 720, 10, "Betriebsspannung"), (300, 720, 10, "10-30 V"),
            (50, 700, 10, "Lichtstrom"), (300, 700, 10, "1.600 lm"),
            (50, 680, 10, "Garantie"), (300, 680, 10, "5 Jahre"),
            (50, 660, 10, "Material"), (300, 660, 10, "Aluminium"),
            (50, 620, 12, "ARTIKELNUMMERN"),
            (50, 600, 10, "SB-100"), (250, 600, 10, "Leuchtbalken Tricolour (gelb/blau/klar)")]
    c = dsi.build(make_pdf([page]), settings, 7).content
    named = [(p["name"], p["wert"]) for p in c["eigenschaften"] if p["wert"]]
    assert named == [("Spannungsbereich", "10-30V"), ("Lichtleistung", "1.600lm"), ("Gehäuse", "Aluminium"),
                     ("", "5 Jahre Garantie")]
    row = ds.tables(c)[0]["zeilen"][0]
    assert row["farbe"] == "gelb/blau/klar"


def test_tricolour_from_subtitle_becomes_colored_suffix(settings):
    page = [(50, 780, 22, "LED LEUCHTBALKEN"), (50, 760, 12, "SERIE SPARTAN TRICOLOUR"),
            (50, 620, 12, "ARTIKELNUMMERN"),
            (50, 600, 10, "RTSB182"), (250, 600, 10, "Leuchtbalken Tricolour (gelb/blau/klar)"),
            (50, 585, 10, "RTSB183"), (250, 585, 10, "Leuchtbalken Tricolour (gelb/blau/klar)")]
    c = dsi.build(make_pdf([page]), settings, 8).content
    assert c["kopf"] == {"titel": "LED Leuchtbalken", "untertitel": "Serie Spartan"}
    assert (c["spez"]["zusatz"], c["spez"]["zusatz_farben"]) == ("Tricolour", "gelb/klar/blau")  # hell in der Mitte


def test_manufacturer_sheet_side_by_side_gets_product_type_and_numbers(settings):
    """Hersteller-Blatt (wie Nordic Lights): Serienname als Titel, Daten zweispaltig nebeneinander,
    Artikelnummern im Fließtext einer Zelle, Fußzeile mit Adresse."""
    page = [(50, 780, 22, "Scorpius GO 410"),
            (50, 740, 10, "Robuster Arbeitsscheinwerfer mit 1900 lm fuer Baumaschinen und Landwirtschaft."),
            (50, 700, 12, "TECHNISCHE DATEN"),
            (50, 680, 10, "Nominale Spannung"), (200, 680, 10, "12 - 24 V"),
            (320, 680, 10, "Artikelnummern"), (450, 680, 10, "Flood (12-24 V): 988-202B,"),
            (200, 668, 10, "36 - 48 V"), (450, 668, 10, "Flood (36-48 V): 988-234B"),
            (50, 650, 10, "Schutzart"), (200, 650, 10, "IP68"), (320, 650, 10, "Gewicht"), (450, 650, 10, "0.5 kg"),
            (50, 630, 10, "Gehaeuse"), (200, 630, 10, "Aluminium"), (320, 630, 10, "Anschluss"), (450, 630, 10, "DT-2"),
            (50, 40, 8, "NORDIC LIGHTS Ltd., P.O. Box 36, www.nordiclights.com")]
    c = dsi.build(make_pdf([page]), settings, 9).content
    assert c["kopf"] == {"titel": "LED Arbeitsscheinwerfer", "untertitel": "Serie Scorpius GO 410"}
    props = {p["name"]: p["wert"] for p in c["eigenschaften"] if p["name"]}
    assert props["Spannungsbereich"] == "12-24V\n36-48V"
    assert props["Wasserdicht"] == "IP68"
    rows = [(r["artnr"], r["beschreibung"]) for t in ds.tables(c) for r in t["zeilen"]]
    assert rows == [("988-202B", "LED Arbeitsscheinwerfer Scorpius GO 410, Flood (12-24 V)"),
                    ("988-234B", "LED Arbeitsscheinwerfer Scorpius GO 410, Flood (36-48 V)")]
    assert "nordiclights" not in json.dumps(c).lower()


def test_title_keeps_own_product_word():
    assert dsi.product_type("Kamera", "Kamerasystem mit Monitor") == "Kamerasystem"


def test_black_line_drawing_on_transparency_is_drawing():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 360, 260), outline=(5, 7, 8, 255), width=3)
    d.line((40, 280, 360, 280), fill=(5, 7, 8, 255), width=2)
    assert dsi._image_kind(img) == "zeichnung"
    filled = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    ImageDraw.Draw(filled).rectangle((40, 40, 360, 260), fill=(5, 7, 8, 255))
    assert dsi._image_kind(filled) is None  # Silhouette/Schattenmaske


def test_english_values_in_bb_spelling():
    assert dsi.bb_value("Spannungsbereich", "10-40 V DC") == "10-40V"
    assert dsi.bb_value("Lichtleistung", "2200 lm") == "2.200lm"
    assert dsi.bb_value("Wasserdicht", "IP67/69K") == "IP67, IP69k"
    assert dsi.bb_value("Wasserdicht", "IP68, IP6K9K") == "IP68, IP6K9K"
    assert dsi.bb_value("Zulassungen", "R10.06") == "ECE-R10"
    assert dsi.bb_value("Gehäuse", "Polycarbonate") == "Kunststoff"
    assert dsi.bb_value("Leuchtbild", "Flood beam") == "Flood"
    assert dsi.bb_value("Zulassungen", "No") == ""
    assert dsi.translate_value("Flexi DIN Pole") == "flexible Rohrmontage"
    assert dsi.translate_value("Mag 70") == "Magnetmontage"
    assert dsi.translate_value("3 Bolt") == "Fixmontage"
    assert dsi.translate_value("DT-2PIN") == "Deutsch Stecker"
    assert dsi.join_mounts(["Fixmontage", "flexible Rohrmontage", "Magnetmontage"]) == "Fix-, Magnet-, flexible Rohrmontage"
    assert dsi.series_name("UNITY WORK LIGHT 31W UNITY WORK LIGHT 31W") == "UNITY"
    assert dsi.series_name("Beacons Serie 400") == "400"


def test_english_sheet_with_model_table(settings):
    """Wie ECCO: Kategorie als Überschrift, „400 Series“, Modelltabelle mit Merkmalsspalten, blitzende Beacons."""
    page = [(50, 790, 20, "BEACONS"), (50, 770, 16, "400 Series"), (50, 755, 12, "R65 LED Beacons"),
            (50, 730, 10, "The 400 Series LED Beacons produce a 360 degree flash pattern for maximum visibility on site."),
            (50, 700, 12, "Models"),
            (50, 685, 9, "PART NO."), (150, 685, 9, "VOLTAGE"), (250, 685, 9, "FPM"), (350, 685, 9, "MOUNT"),
            (50, 672, 9, "V11050*"), (150, 672, 9, "10-30V"), (250, 672, 9, "125"), (350, 672, 9, "3 Bolt"),
            (50, 660, 9, "V11054"), (150, 660, 9, "10-30V"), (250, 660, 9, "125"), (350, 660, 9, "Mag 70"),
            (50, 648, 9, "V11055"), (150, 648, 9, "10-30V"), (250, 648, 9, "125"), (350, 648, 9, "Flexi DIN Pole")]
    c = dsi.build(make_pdf([page]), settings, 10).content
    assert c["kopf"] == {"titel": "LED Blitzleuchten", "untertitel": "Serie 400"}
    props = {p["name"]: p["wert"] for p in c["eigenschaften"] if p["name"]}
    assert props["Spannungsbereich"] == "10-30V"
    assert props["Montage"] == "Fix-, Magnet-, flexible Rohrmontage"
    assert props["Zulassungen"] == "ECE-R65"
    rows = [(r["artnr"], r["beschreibung"]) for t in ds.tables(c) for r in t["zeilen"]]
    assert rows[0] == ("V11050", "LED Blitzleuchte, 10-30V, Fixmontage")
    assert rows[2] == ("V11055", "LED Blitzleuchte, 10-30V, flexible Rohrmontage")


def test_english_single_model_sheet(settings):
    """Wie Strands: ein Modell, „Part No.“, Datentabelle ohne Überschrift, zwei Spalten nebeneinander."""
    page = [(50, 800, 10, "Part No. 809237"), (50, 780, 18, "UNITY WORK LIGHT 31W"), (50, 765, 10, "10-40V | FLOOD BEAM"),
            (50, 740, 10, "Become a professional with the Unity series. Comes with a smooth look and strong light."),
            (50, 700, 9, "Voltage (DC)"), (180, 700, 9, "10-40 V DC"), (320, 700, 9, "Cable length"), (450, 700, 9, "520 mm"),
            (50, 688, 9, "Consumption"), (180, 688, 9, "29 W"), (320, 688, 9, "Color lens"), (450, 688, 9, "Clear"),
            (50, 676, 9, "Actual lumen"), (180, 676, 9, "2200 lm"), (320, 676, 9, "IP-class"), (450, 676, 9, "IP67/69K"),
            (50, 664, 9, "Beam pattern"), (180, 664, 9, "Flood beam"), (320, 664, 9, "E-approved"), (450, 664, 9, "No"),
            (50, 652, 9, "Connection"), (180, 652, 9, "DT-2PIN"), (320, 652, 9, "ECE approval"), (450, 652, 9, "R10.06")]
    c = dsi.build(make_pdf([page]), settings, 11).content
    assert c["kopf"] == {"titel": "LED Arbeitsscheinwerfer", "untertitel": "Serie Unity"}
    props = {p["name"]: p["wert"] for p in c["eigenschaften"] if p["name"]}
    assert props["Spannungsbereich"] == "10-40V"
    assert props["Lichtleistung"] == "2.200lm gemessen"
    assert props["Wasserdicht"] == "IP67, IP69k"
    assert props["Zulassungen"] == "ECE-R10"
    assert props["Leuchtbild"] == "Flood"
    bullets = [p["wert"] for p in c["eigenschaften"] if not p["name"]]
    assert "52cm Anschlusskabel mit Deutsch Stecker" in bullets
    rows = [(r["artnr"], r["beschreibung"]) for t in ds.tables(c) for r in t["zeilen"]]
    assert rows == [("809237", "LED Arbeitsscheinwerfer, mit 52cm Anschlusskabel & Deutsch Stecker, 10-40V, 31W")]


def test_rotating_beacon_stays_rundumleuchte():
    assert dsi.product_type("", "LED beacon with rotating light and flash mode") == "Rundumleuchte"
    assert dsi.product_type("", "LED beacon, 125 FPM double flash") == "Blitzleuchte"
