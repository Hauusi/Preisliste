"""Design-Vorlagen: unsere Original-PDFs; das Tool liest nur ab (Bilder, Text, Zeilen, Artikel) und baut neue Blätter
aus Herstellerblättern danach – nie werden Werte, Artikel oder Bilder der Vorlagen übernommen."""

import json
import re

from backend.ai.provider import MockProvider, set_provider
from backend.database.engine import session_scope
from backend.models.entities import Datasheet, DatasheetExample
from backend.services import datasheet_examples as dse
from backend.services import datasheets as ds
from tests.conftest import run_jobs
from tests.pdf_factory import make_pdf
from tests.test_datasheet_import import _pdf

OURS = [(50, 780, 22, "LED BLITZLEUCHTEN"), (50, 760, 12, "SERIE 400"),
        (50, 700, 10, "Die Blitzleuchten der Serie 400 bieten eine Doppelblitz Funktion und drei Montageversionen."),
        (50, 670, 10, "•  3 Jahre Garantie"),
        (50, 640, 12, "SPEZIFIKATIONEN"),
        (50, 620, 10, "Spannungsbereich:"), (250, 620, 10, "10-30V"),
        (50, 605, 10, "Montage:"), (250, 605, 10, "Fixmontage"),
        (50, 590, 10, "Blitzmuster:"), (250, 590, 10, "Doppelblitz"),
        (50, 420, 12, "BESTELLINFORMATIONEN"),
        (50, 400, 10, "VAV11050"), (200, 400, 10, "LED Blitzleuchte, gelbe Linse, 10-30V, Fixmontage")]


def _example_pdf():
    return make_pdf([OURS], image_on_page=0)  # Produktbild rechts oben, ca. 71 x 49 mm


def test_analyze_reads_layout_text_and_rows_without_building_a_sheet(settings):
    p = dse.analyze(_example_pdf(), settings)
    assert p["art"] == "Blitzleuchte" and p["titel"] == "LED Blitzleuchten"
    assert p["text"].startswith("Die Blitzleuchten der Serie 400")
    assert p["punkte"] == ["3 Jahre Garantie"]
    assert p["eigenschaften"] == ["Spannungsbereich", "Montage"] and p["spez"] == ["Blitzmuster"]
    assert p["artikel"] == ["LED Blitzleuchte, gelbe Linse, 10-30V, Fixmontage"]
    [img] = p["bilder"]
    assert img["art"] == "produkt" and img["seite"] == 0 and round(img["x"]) == 116 and round(img["h"]) == 49
    assert not (settings.upload_dir / "datenblatt" / "0").exists()  # nichts gespeichert


def test_design_by_kind_else_all_and_apply():
    a = {"art": "Blitzleuchte", "profil": {"bilder": [{"seite": 0, "art": "produkt", "x": 104, "y": 45, "w": 60, "h": 40}],
                                           "eigenschaften": ["Montage", "Spannungsbereich"], "spez": ["Blitzmuster"],
                                           "punkte": ["3 Jahre Garantie"], "text": "Text A", "artikel": ["Art A"]}}
    b = {"art": "Scheinwerfer", "profil": {"bilder": [], "eigenschaften": [], "spez": [], "punkte": [], "text": "Text B",
                                           "artikel": []}}
    profiles, by_kind = dse.choose([a, b], "Blitzleuchte")
    assert by_kind and len(profiles) == 1
    profiles, by_kind = dse.choose([a, b], "Ampel")
    assert not by_kind and len(profiles) == 2
    profiles, by_kind = dse.choose([a, b], "Arbeitsscheinwerfer")  # verwandte Art
    assert by_kind and profiles == [b["profil"]]
    rules = dse.design([a["profil"]])
    assert rules["aufteilung"] == "bild" and rules["produktbilder"] == 1 and not rules["anwendung"]
    c = ds.empty_content()
    c["eigenschaften"] = [{"name": "Spannungsbereich", "wert": "12-24V", "sichtbar": True},
                          {"name": "", "wert": "Synchronisierbar", "sichtbar": True}]
    c["bilder_oben"] = ["1" * 16 + ".png", "2" * 16 + ".png"]
    c["bilder_unten"] = ["3" * 16 + ".jpg"]
    out = dse.apply(c, rules)
    assert [(p["name"], p["wert"], p["sichtbar"]) for p in out["eigenschaften"]] == [
        ("Montage", "", True), ("Spannungsbereich", "12-24V", True),
        ("", "3 Jahre Garantie", False), ("", "Synchronisierbar", True)]
    assert out["bilder_oben"] == ["1" * 16 + ".png"] and out["aufteilung"] == "bild"
    assert out["bild_groesse"] == {"1" * 16: 70}  # 40 mm statt 56 mm
    assert [b["sichtbar"] for b in out["bloecke"] if b["typ"] == "anwendung"] == [False]


def test_library_admin_only_original_pdf_kept_nothing_rebuilt(admin_client, user_client, app, settings):
    c = admin_client
    assert user_client.get("/datenblatt/vorlagen").status_code == 403
    assert "/datenblatt/vorlagen" not in user_client.get("/datenblatt").text
    before = c.get("/datenblatt").text
    r = c.post("/datenblatt/vorlagen", data={"csrf_token": c.csrf},
               files=[("dateien", ("a.pdf", _example_pdf(), "application/pdf")),
                      ("dateien", ("b.pdf", _pdf(), "application/pdf"))], follow_redirects=False)
    assert r.headers["location"].startswith("/jobs/")
    run_jobs(app)
    target = re.search(r'content="0;url=([^"]+)"', c.get(r.headers["location"]).text).group(1)
    page = c.get(target).text
    assert "So baut das Tool neue Datenblätter" in page and "Blitzleuchte" in page
    with session_scope() as db:
        examples = db.query(DatasheetExample).order_by(DatasheetExample.id).all()
        assert [e.filename for e in examples] == ["a.pdf", "b.pdf"] and all(e.profile for e in examples)
        assert examples[0].kind == "Blitzleuchte" and examples[0].title == "LED Blitzleuchten – Serie 400"
        assert db.query(Datasheet).count() == 0  # kein nachgebautes Datenblatt
        eid = examples[0].id
    assert c.get("/datenblatt").text.count("<tr") == before.count("<tr")
    pdf = c.get(f"/datenblatt/vorlagen/{eid}/pdf")
    assert pdf.status_code == 200 and pdf.content == _example_pdf()  # Original unverändert
    assert user_client.get(f"/datenblatt/vorlagen/{eid}/pdf").status_code == 403
    c.post(f"/datenblatt/vorlagen/{eid}/art", data={"csrf_token": c.csrf, "art": "Blitzleuchte, Blitzmodul"})
    c.post(f"/datenblatt/vorlagen/{eid}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    with session_scope() as db:
        assert db.get(DatasheetExample, eid) is None
    assert not dse.pdf_path(settings, eid).exists()


def test_import_follows_examples_and_ai_writes_in_our_style(admin_client, app, settings):
    c = admin_client
    profile = dse.analyze(_example_pdf(), settings)
    with session_scope() as db:
        db.add(DatasheetExample(filename="a.pdf", kind="Blitzleuchte", profile=profile))
    text = json.dumps({"beschreibung": "Die Blitzleuchten der Serie Test sind robust und einfach zu montieren.",
                       "punkte": []})
    arts = json.dumps({"texte": ["LED Blitzleuchte, gelb, 12 V DC", "LED Blitzleuchte, gelb, 24 V DC"]})
    ai = MockProvider(settings, [text, arts])
    set_provider(ai)
    try:
        r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf},
                   files={"datei": ("h.pdf", _pdf(), "application/pdf")}, follow_redirects=False)
        run_jobs(app)
    finally:
        set_provider(None)
    target = re.search(r'content="0;url=([^"]+)"', c.get(r.headers["location"]).text).group(1)
    editor = c.get(target).text
    assert "Design wie in 1 unserer Datenblätter dieser Produktart" in editor
    assert "Doppelblitz Funktion" in ai.prompts[0]  # unser Text als Stilvorbild
    assert "LED Blitzleuchte, gelbe Linse, 10-30V, Fixmontage" in ai.prompts[1]  # unsere Artikel als Vorbild
    with session_scope() as db:
        sheet = db.query(Datasheet).order_by(Datasheet.id.desc()).first()
        rows = [r_["beschreibung"] for t in ds.tables(sheet.content) for r_ in t["zeilen"]]
        assert rows[:2] == ["LED Blitzleuchte, gelb, 12 V DC", "LED Blitzleuchte, gelb, 24 V DC"]
        assert sheet.content["eigenschaften"][0]["name"] == "Spannungsbereich"
        assert "VAV11050" not in json.dumps(sheet.content)  # nichts aus der Vorlage übernommen


def test_article_ai_must_keep_numbers(settings):
    bad = json.dumps({"texte": ["LED Blitzleuchte, 99 V"]})
    ai = MockProvider(settings, [bad, bad, bad])
    try:
        ai.article_texts(["LED Blitzleuchte, 12 V DC"], ["Beispiel"])
        assert False, "erfundene Zahl muss abgelehnt werden"
    except Exception as exc:  # noqa: BLE001
        assert "Zahlen" in str(exc)
