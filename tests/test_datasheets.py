"""Datenblatt: Editor mit Bausteinen, automatisches Speichern + Live-Vorschau, Bilder, Seitenaufteilung, Sichtbarkeit."""

import base64
import re

from backend.services import datasheets as ds

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAAABJRU5ErkJggg==")


def _new(c, titel="LED Blitzmodule", untertitel="Serie Gecko") -> int:
    r = c.post("/datenblatt/neu", data={"csrf_token": c.csrf, "titel": titel, "untertitel": untertitel},
               follow_redirects=False)
    assert r.status_code == 303 and re.fullmatch(r"/datenblatt/\d+", r.headers["location"])
    return int(r.headers["location"].rsplit("/", 1)[1])


def _upload(c, sid, name="a.png", data=PNG):
    return c.post(f"/datenblatt/{sid}/bilder", files={"datei": (name, data, "image/png")},
                  headers={"X-CSRF-Token": c.csrf})


def _save(c, sid, content):
    return c.post(f"/datenblatt/{sid}/inhalt", json={"inhalt": content}, headers={"X-CSRF-Token": c.csrf})


def _content(**kw):
    c = ds.empty_content()
    c["kopf"] = {"titel": "LED Leuchtbalken", "untertitel": "Serie 12+"}
    c.update(kw)
    return c


def test_portal_tile_and_create(admin_client):
    c = admin_client
    page = c.get("/").text
    assert 'href="/datenblatt"' in page and "0 Datenblätter" in page
    r = c.post("/datenblatt/neu", data={"csrf_token": c.csrf, "titel": " "}, follow_redirects=False)
    assert r.headers["location"].startswith("/datenblatt?error=")
    sid = _new(c)
    page = c.get(f"/datenblatt/{sid}").text
    assert "Live-Vorschau" in page and 'data-blocks' in page and "LED BLITZMODULE" not in page
    assert "<h1>LED Blitzmodule</h1>" in page  # Kopfzeile in der Vorschau
    assert c.get(f"/datenblatt/{sid}/schritt/kopf", follow_redirects=False).headers["location"] == f"/datenblatt/{sid}"


def test_save_returns_live_preview_with_all_blocks(admin_client, settings):
    c = admin_client
    sid = _new(c)
    img = [_upload(c, sid).json()["name"] for _ in range(4)]
    content = _content(
        eigenschaften=[{"name": "Garantie", "wert": "5 Jahre", "sichtbar": True},
                       {"name": "Spannung", "wert": "12-24V", "sichtbar": False},
                       {"name": "Montage", "wert": "", "sichtbar": True}],
        bilder_oben=[img[0], "../../etc/passwd", "fremd.png"],
        spez={"zeilen": [{"merkmal": "Zulassungen", "wert": "ECE-R65, ECE-R10, CISPR 25"},
                         {"merkmal": "Abmessungen", "wert": "L x 279 x 64mm\nL x 279 x 99mm"}]},
        bloecke=[{"typ": "intro"}, {"typ": "spez"}, {"typ": "bild", "bild": img[1], "hoehe": "S"},
                 {"typ": "tabelle", "titel": "Bestellinformationen", "zusatz": "Serie 12+ Standard Version",
                  "bild": img[2], "bild_pos": "oben", "zeilenbilder": "klein", "spalten": ["Länge", "", ""],
                  "zeilen": [{"bild": img[3], "artnr": "VA12-30177-E", "farbe": "gelb",
                              "beschreibung": "12 LED Blitzmodule, gelb, klare Linsen", "werte": ["1.070mm"]}]},
                 {"typ": "tabelle", "titel": "Zubehör", "zeilenbilder": "gross", "spalten": ["Brutto VK"],
                  "zeilen": [{"artnr": "EZ0006", "beschreibung": "Steuerung", "werte": ["€ 219,30"]}]},
                 {"typ": "anwendung", "sichtbar": False}])
    r = _save(c, sid, content)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] and data["titel"] == "LED Leuchtbalken – Serie 12+" and data["seiten"] == 1
    html = data["html"]
    # Eigenschaft mit Namen steht in der Spezifikationstabelle vor den eigenen Zeilen
    assert "<tr><th>Garantie:</th><td>5 Jahre</td></tr>" in html and "<li>" not in html
    assert html.index("Garantie:") < html.index("Zulassungen:") and "12-24V" not in html  # ausgeblendet
    assert html.count('class="ece-in"') == 3 and "CISPR 25" in html and 'class="ece cispr"' in html
    assert "L x 279 x 64mm<br>L x 279 x 99mm" in html
    assert "<b>Bestellinformationen</b> - Serie 12+ Standard Version" in html
    assert 'class="banner"' in html and 'class="rowimg"' in html and "€ 219,30" in html
    assert 'class="part free-img h-S"' in html
    # gespeichert und gesäubert: nur eigene Bilder, Reihenfolge der Bausteine bleibt
    stored = c.get(f"/datenblatt/{sid}").text
    assert stored.index('data-typ="bild"') < stored.index('data-typ="tabelle"')
    from backend.database.engine import session_scope
    from backend.models.entities import Datasheet

    with session_scope() as db:
        saved = db.get(Datasheet, sid).content
    assert saved["bilder_oben"] == [img[0]]
    assert [b["typ"] for b in saved["bloecke"]] == ["intro", "spez", "bild", "tabelle", "tabelle", "anwendung"]
    assert saved["bloecke"][3]["spalten"] == ["Länge"] and saved["bloecke"][5]["sichtbar"] is False
    # Druckansicht nutzt dieselbe Vorlage
    page = c.get(f"/datenblatt/{sid}/vorschau").text
    assert "<b>Bestellinformationen</b>" in page and "Braun &amp; Braun GmbH" in page


def test_new_page_and_order_control_pagination():
    c = _content(eigenschaften=[{"name": "", "wert": "1", "sichtbar": True}], kopf={"titel": "", "untertitel": ""})
    rows = [{"bild": None, "artnr": f"A{i}", "farbe": "", "beschreibung": "x", "werte": []} for i in range(3)]
    table = {**ds.new_table("Tabelle"), "zeilen": rows}
    c["bloecke"] = [{"typ": "intro", "neue_seite": False, "sichtbar": True}, table]
    assert len(ds.paginate(c)) == 1
    c["bloecke"][1] = {**table, "neue_seite": True}
    pages = ds.paginate(c)
    assert len(pages) == 2 and pages[1]["teile"][0]["titel"] == "Tabelle"
    # Reihenfolge der Bausteine bestimmt die Reihenfolge im Blatt
    c["bloecke"] = [{**table, "neue_seite": False}, {"typ": "intro", "neue_seite": False, "sichtbar": True}]
    assert [t["typ"] for t in ds.paginate(c)[0]["teile"]] == ["tabelle", "kopfbereich"]


def test_long_tables_are_split_with_continuation():
    rows = [{"bild": None, "artnr": f"A{i}", "farbe": "", "beschreibung": "x", "werte": []} for i in range(60)]
    c = _content()
    c["bloecke"].append({**ds.new_table("Gross"), "zeilen": rows})
    c["bloecke"].append({**ds.new_table(zubehoer=True),
                         "zeilen": [{"bild": "x.png", "artnr": f"Z{i}", "farbe": "", "beschreibung": "", "werte": []}
                                    for i in range(15)]})
    pages = ds.paginate(c)
    parts = [t for p in pages for t in p["teile"]]
    shown = [r["artnr"] for t in parts if t.get("titel") == "Gross" for r in t["zeilen"]]
    assert shown == [r["artnr"] for r in rows]
    assert any(t.get("fortsetzung") for t in parts)
    assert sum(len(t["zeilen"]) for t in parts if t.get("titel") == "Zubehör") == 15


def test_images_upload_validation_swap_and_cleanup(admin_client, settings):
    c = admin_client
    sid = _new(c)
    r = _upload(c, sid, "boese.svg", b"<svg onload=alert(1)>")
    assert r.status_code == 400 and "ist kein Bild" in r.json()["detail"]
    a, b = _upload(c, sid).json()["name"], _upload(c, sid).json()["name"]
    img = c.get(f"/datenblatt/{sid}/bild/{a}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content.startswith(b"\x89PNG")
    _save(c, sid, _content(bilder_oben=[b, a]))
    # Nicht verwendete Bilder werden erst nach der Schonfrist gelöscht (Upload und Speichern laufen getrennt)
    _save(c, sid, _content(bilder_oben=[b]))
    assert len(ds.image_names(settings, sid)) == 2
    ds.remove_unused_images(settings, sid, _content(bilder_oben=[b]))
    assert ds.image_names(settings, sid) == {b}
    assert c.get(f"/datenblatt/{sid}/bild/..%2F..%2Fpreisliste.sqlite3").status_code == 404


def test_save_requires_csrf_and_rejects_garbage(admin_client):
    c = admin_client
    sid = _new(c)
    r = c.post(f"/datenblatt/{sid}/inhalt", json={"inhalt": {}})
    assert r.status_code == 403
    r = _save(c, sid, {"kopf": "kaputt", "bloecke": [{"typ": "boese"}, "x", {"typ": "tabelle", "zeilen": "nein"}],
                       "eigenschaften": [{"name": ["liste"], "wert": 5}]})
    assert r.status_code == 200
    from backend.database.engine import session_scope
    from backend.models.entities import Datasheet

    with session_scope() as db:
        saved = db.get(Datasheet, sid).content
    assert [b["typ"] for b in saved["bloecke"]] == ["intro", "spez", "anwendung", "tabelle"]
    assert saved["eigenschaften"] == [{"name": "", "wert": "5", "sichtbar": True}]


def test_paste_rows_from_excel(admin_client):
    c = admin_client
    sid = _new(c)
    r = c.post(f"/datenblatt/{sid}/einfuegen", headers={"X-CSRF-Token": c.csrf},
               json={"text": "RTG3HSB0CB\tLED Blitzmodul Gecko 3, 11-30V, blau\tECE-R65 Klasse I\tHorizontal\n"
                             "RTG3HSW0CB;LED Blitzmodul Gecko 3, 11-30V, klar;ECE-R65 Klasse I", "spalten": 2})
    rows = r.json()["zeilen"]
    assert [x["artnr"] for x in rows] == ["RTG3HSB0CB", "RTG3HSW0CB"]
    assert rows[0]["farbe"] == "blau" and rows[1]["farbe"] == "klar"
    assert rows[0]["werte"] == ["ECE-R65 Klasse I", "Horizontal"] and rows[1]["werte"] == ["ECE-R65 Klasse I", ""]


def test_old_format_is_migrated_to_blocks():
    old = {"kopf": {"titel": "A", "untertitel": ""}, "beschreibung": {"text": "x", "punkte": ["2 Jahre Garantie"]},
           "gruppen": [{"titel": "Gecko 3", "bild": "g.png", "spalten": ["Zulassung"],
                        "zeilen": [{"artnr": "R1", "farbe": "gelb", "beschreibung": "b", "werte": ["ECE"]}]}],
           "zubehoer": [{"bild": "z.png", "artnr": "Z1", "beschreibung": "Winkel"}]}
    c = ds.normalized(old)
    assert c["eigenschaften"][0] == {"name": "", "wert": "2 Jahre Garantie", "sichtbar": True}
    assert c["einleitung"] == "x"  # früherer Beschreibungstext bleibt erhalten
    typs = [b["typ"] for b in c["bloecke"]]
    assert typs == ["intro", "spez", "anwendung", "tabelle", "tabelle"]
    gecko, acc = c["bloecke"][3], c["bloecke"][4]
    assert gecko["titel"] == "Gecko 3" and gecko["bild_pos"] == "links" and gecko["neue_seite"]
    assert acc["titel"] == "Zubehör" and acc["zeilen"][0]["bild"] == "z.png" and acc["zeilenbilder"] == "gross"
    assert ds.referenced_images(old) == {"g.png", "z.png"}


def test_copy_delete_and_user_isolation(admin_client, user_client, settings):
    sid = _new(user_client, "Arbeitsscheinwerfer", "Serie X")
    _upload(user_client, sid)
    other = _new(admin_client, "Admin-Blatt", "")
    assert user_client.get(f"/datenblatt/{other}").status_code == 404
    assert _save(user_client, other, _content()).status_code == 404
    assert "Admin-Blatt" not in user_client.get("/datenblatt").text
    assert "Arbeitsscheinwerfer" in admin_client.get("/datenblatt").text

    r = user_client.post(f"/datenblatt/{sid}/kopieren", data={"csrf_token": user_client.csrf}, follow_redirects=False)
    copy_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert len(ds.image_names(settings, copy_id)) == 1
    assert "Arbeitsscheinwerfer – Serie X (Kopie)" in user_client.get("/datenblatt").text

    r = user_client.post(f"/datenblatt/{sid}/loeschen", data={"csrf_token": user_client.csrf, "bestaetigt": "ja"},
                         follow_redirects=False)
    assert r.status_code == 303
    assert not ds.image_dir(settings, sid).exists()
    assert user_client.get(f"/datenblatt/{sid}/vorschau").status_code == 404
    assert ds.image_dir(settings, copy_id).exists()


def test_guess_color_from_description():
    assert ds.guess_color("LED Blitzmodul Gecko 3, 11-30V, gelb") == "gelb"
    assert ds.guess_color("Blitzer, blau/weiß") == "weiss"
    assert ds.guess_color("Winkel für Gecko 3") == ""


def test_approval_badges_from_zulassung():
    c = ds.empty_content()
    c["eigenschaften"] = [{"name": "Zulassung", "wert": "ECE-R10, ECE-R65", "sichtbar": False}]
    assert ds.approval_badges(c) == [{"art": "ECE", "nr": "10", "klasse": None}, {"art": "ECE", "nr": "65", "klasse": None}]
    c["eigenschaften"][0]["wert"] = "ECE-R65 Klasse I (Gecko 3), ECE-R65 Klasse II (Gecko 6), R 10, CISPR 25"
    assert ds.approval_badges(c) == [{"art": "ECE", "nr": "65", "klasse": "2"}, {"art": "ECE", "nr": "10", "klasse": None},
                                     {"art": "CISPR", "nr": "25", "klasse": None}]
    c["eigenschaften"][0]["wert"] = "E-Prüfzeichen"
    c["spez"]["zeilen"] = [{"merkmal": "Zulassungen", "wert": "ECE R148"}, {"merkmal": "Spannung", "wert": "R12"}]
    assert ds.approval_badges(c) == [{"art": "ECE", "nr": "148", "klasse": None}]


def test_intro_text_and_spec_share_head_area_like_standard(admin_client):
    """Standard-Aufbau: links Beschreibungstext, Aufzählung, Spezifikation; rechts Bilder über die ganze Höhe."""
    c = admin_client
    sid = _new(c, "LED Leuchtbalken", "Serie 12+")
    img = _upload(c, sid).json()["name"]
    html = _save(c, sid, _content()).json()["html"]
    assert 'class="placeholder"' in html  # leerer Text: Platz in der Live-Vorschau sichtbar
    assert 'class="placeholder"' not in c.get(f"/datenblatt/{sid}/vorschau").text  # nicht im Druck
    content = _content(einleitung="Die LED Leuchtbalken der Serie 12+ Vantage sind leistungsstark.\n\nZweiter Absatz.",
                       eigenschaften=[{"name": "", "wert": "5 Jahre Garantie", "sichtbar": True}],
                       bilder_oben=[img], spez={"zeilen": [{"merkmal": "Spannungsbereich", "wert": "12-24V"}]})
    html = _save(c, sid, content).json()["html"]
    assert html.count('class="part lead"') == 1 and 'class="placeholder"' not in html
    left = html[html.index('class="lead-left"'):html.index('class="lead-right"')]
    assert left.index("Vantage sind leistungsstark.</p>") < left.index("<li>5 Jahre Garantie</li>") < left.index("Spannungsbereich")
    assert "<p>Zweiter Absatz.</p>" in left
    assert img in html[html.index('class="lead-right"'):]
    # Spezifikation mit „neue Seite“: eigener Kopfbereich auf Seite 2
    content["bloecke"] = [{"typ": "intro"}, {"typ": "spez", "neue_seite": True}, {"typ": "anwendung"}]
    data = _save(c, sid, content).json()
    assert data["seiten"] == 2 and data["html"].count('class="part lead"') == 2


def test_spec_heading_from_product_type_and_series(admin_client):
    """Überschrift wie im Standard („LED Leuchtbalken - Serie 12+ / Spezifikationen“) steht sofort,
    auch ohne Spezifikationszeilen – in der Live-Vorschau und im Druck."""
    c = admin_client
    sid = _new(c, "LED Leuchtbalken", "Serie 12+")
    title = '<h2 class="part-title"><b>LED Leuchtbalken</b> - Serie 12+<small>Spezifikationen</small></h2>'
    assert title in _save(c, sid, _content()).json()["html"]
    assert title in c.get(f"/datenblatt/{sid}/vorschau").text
    content = _content(kopf={"titel": "", "untertitel": ""})
    assert "Produkttyp - Serie</span><small>Spezifikationen" in _save(c, sid, content).json()["html"]
    assert "<small>Spezifikationen</small>" not in c.get(f"/datenblatt/{sid}/vorschau").text


def test_named_properties_go_into_spec_table(admin_client):
    """„Spannung: 12-24V“ gehört unter „Spezifikationen“, Punkte ohne Namen bleiben Aufzählung unter dem Text."""
    c = admin_client
    sid = _new(c, "LED Blitzmodul", "Serie Flashy")
    content = _content(kopf={"titel": "LED Blitzmodul", "untertitel": "Serie Flashy"},
                       einleitung="Die LED Blitzmodule der Serie Flashy sind mega flashy.",
                       eigenschaften=[{"name": "Spannung", "wert": "12-24V", "sichtbar": True},
                                      {"name": "LED-Farbe", "wert": "gelb", "sichtbar": True},
                                      {"name": "", "wert": "5 Jahre Garantie", "sichtbar": True},
                                      {"name": "Schutzart", "wert": "IP67", "sichtbar": True}],
                       spez={"zeilen": [{"merkmal": "Schutzart:", "wert": "IP69K"}]})
    html = _save(c, sid, content).json()["html"]
    intro = html[html.index('class="lead-intro"'):html.index('class="lead-spec"')]
    spec = html[html.index('class="lead-spec"'):html.index('class="lead-right"')]
    assert "<li>5 Jahre Garantie</li>" in intro and "Spannung" not in intro
    assert spec.index("Spezifikationen") < spec.index("<th>Spannung:</th><td>12-24V</td>") < spec.index("LED-Farbe")
    assert "IP69K" in spec and "IP67" not in html  # eigene Spezifikationszeile geht vor
    # Spezifikation ausgeblendet: Eigenschaften bleiben als Aufzählung oben
    content["bloecke"] = [{"typ": "intro"}, {"typ": "spez", "sichtbar": False}]
    html = _save(c, sid, content).json()["html"]
    assert "<li><b>Spannung:</b> 12-24V</li>" in html and "Spezifikationen" not in html


def _photo(fmt: str, bg=(255, 255, 255)) -> bytes:
    """Produktfoto wie vom Hersteller: einfarbiger Hintergrund, Produkt mit heller Fläche innen."""
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", (300, 200), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((60, 50, 240, 150), fill=(230, 120, 0))
    d.rectangle((100, 80, 200, 120), fill=bg)  # helle Fläche im Produkt, nicht mit dem Rand verbunden
    out = io.BytesIO()
    im.save(out, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    return out.getvalue()


def test_product_images_are_cut_out_as_png_application_images_unchanged(admin_client):
    import io

    from PIL import Image

    c = admin_client
    sid = _new(c)
    for fmt, name in (("JPEG", "a.jpg"), ("WEBP", "a.webp"), ("PNG", "a.png")):
        r = _upload(c, sid, name, _photo(fmt))
        assert r.status_code == 200 and r.json()["name"].endswith(".png"), (fmt, r.text)
        im = Image.open(io.BytesIO(c.get(r.json()["url"]).content))
        w, h = im.size
        assert im.mode == "RGBA" and 185 <= w <= 200 and 105 <= h <= 120  # auf das Produkt zugeschnitten
        assert im.getpixel((0, 0))[3] == 0  # Hintergrund transparent
        assert im.getpixel((15, 15))[3] == 255  # Produkt deckend
        assert im.getpixel((w // 2, h // 2))[3] == 255  # helle Fläche im Produkt bleibt
    # Anwendungsbild (Foto mit Umgebung): bleibt wie geliefert
    data = _photo("WEBP")
    r = c.post(f"/datenblatt/{sid}/bilder", headers={"X-CSRF-Token": c.csrf},
               files={"datei": ("b.webp", data, "image/webp")}, data={"art": "anwendung"})
    assert r.json()["name"].endswith(".webp") and c.get(r.json()["url"]).content == data
    # Ohne einfarbigen Rand (echtes Foto): nichts entfernen, nur PNG
    noisy = Image.effect_noise((120, 80), 80).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, "JPEG")
    im = Image.open(io.BytesIO(c.get(_upload(c, sid, "n.jpg", buf.getvalue()).json()["url"]).content))
    assert im.size == (120, 80) and im.getchannel("A").getextrema() == (255, 255)
    # Beschädigtes Bild mit gültigem Kopf
    r = _upload(c, sid, "kaputt.png", PNG[:30])
    assert r.status_code == 400 and "beschädigt" in r.json()["detail"]
