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
    assert ds.guess_color("Blitzer, blau/weiß") == "blau/weiss"  # mehrfarbig: Tortenstücke
    assert ds.guess_color("LED Leuchtbalken, Tricolour (gelb/blau/klar), klare Linsen") == "gelb/blau/klar"
    assert ds.guess_color("LED rot/grün, 12 V DC") == "rot/gruen"
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


def test_product_images_are_cut_out_as_png_application_images_unchanged(admin_client, settings):
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
    plain = _upload(c, sid, "n.jpg", buf.getvalue()).json()
    im = Image.open(io.BytesIO(c.get(plain["url"]).content))
    assert im.size == (120, 80) and im.getchannel("A").getextrema() == (255, 255) and plain["zweitfassung"] is None
    assert c.post(f"/datenblatt/{sid}/bild/{plain['name']}/hintergrund",
                  headers={"X-CSRF-Token": c.csrf}).status_code == 404
    # „Hintergrund behalten“: zwischen freigestellt und Original wechseln, beide bleiben beim Aufräumen erhalten
    photo = _photo("JPEG")
    cut = _upload(c, sid, "p.jpg", photo).json()
    assert cut["zweitfassung"] == cut["name"].replace(".png", "-o.jpg")
    assert cut["name"] in c.get(f"/datenblatt/{sid}").text  # Editor kennt die zweite Fassung
    r = c.post(f"/datenblatt/{sid}/bild/{cut['name']}/hintergrund", headers={"X-CSRF-Token": c.csrf}).json()
    assert r["name"] == cut["zweitfassung"] and r["hintergrund"] and c.get(r["url"]).content == photo
    back = c.post(f"/datenblatt/{sid}/bild/{r['name']}/hintergrund", headers={"X-CSRF-Token": c.csrf}).json()
    assert back["name"] == cut["name"] and not back["hintergrund"]
    assert c.post(f"/datenblatt/{sid}/bild/{cut['name']}/hintergrund").status_code in (400, 403)  # CSRF
    _save(c, sid, _content(bilder_oben=[r["name"]]))
    ds.remove_unused_images(settings, sid, _content(bilder_oben=[r["name"]]))
    assert ds.image_names(settings, sid) == {cut["name"], cut["zweitfassung"]}
    # Beschädigtes Bild mit gültigem Kopf
    r = _upload(c, sid, "kaputt.png", PNG[:30])
    assert r.status_code == 400 and "beschädigt" in r.json()["detail"]


def test_empty_table_shows_in_live_preview_only(admin_client):
    """Tabelle mit Überschrift/Bild, aber ohne Artikelzeilen: in der Live-Vorschau sichtbar mit Hinweis, im Druck nicht."""
    c = admin_client
    sid = _new(c, "LED Blitzmodul", "Serie Flashy")
    img = _upload(c, sid).json()["name"]
    table = {**ds.new_table("Flashy 3"), "zusatz": "Flashy 3", "bild": img, "bild_pos": "links",
             "spalten": ["Zulassung", "Montage"], "zeilen": []}
    html = _save(c, sid, _content(bloecke=[{"typ": "intro"}, {"typ": "spez"}, table])).json()["html"]
    assert "<b>Flashy 3</b> - Flashy 3" in html and "Noch keine Artikel" in html and img in html
    page = c.get(f"/datenblatt/{sid}/vorschau").text
    assert "Flashy 3" not in page and "Noch keine Artikel" not in page


def test_product_images_can_be_moved_by_offset(admin_client):
    """Produktbilder oben rechts: Versatz per Maus wird gespeichert, begrenzt und in Vorschau und Druck angewendet."""
    c = admin_client
    sid = _new(c)
    a, b = _upload(c, sid).json()["name"], _upload(c, sid).json()["name"]
    ka, kb = ds.image_key(a), ds.image_key(b)
    r = _save(c, sid, _content(bilder_oben=[a, b], bild_versatz={ka: [12.26, -4], kb: [999, "x"],
                                                                  "fremd": [1, 1]}))
    assert r.status_code == 200
    assert f'data-move="{ka}"' in r.json()["html"]  # Editor: Bild ist greifbar
    assert 'data-offset="12.5 -4.0"' in r.json()["html"] and "style=" not in r.json()["html"]  # CSP: kein Inline-Style
    saved = ds.normalized(_saved(c, sid))
    assert saved["bild_versatz"] == {ka: [12.5, -4.0]}  # gerundet, ungültig und fremd verworfen
    page = c.get(f"/datenblatt/{sid}/vorschau").text
    assert 'data-offset="12.5 -4.0"' in page and "data-move" not in page  # Druck: verschoben, nicht greifbar
    # Bild entfernt -> Versatz verschwindet
    _save(c, sid, _content(bilder_oben=[b], bild_versatz={ka: [5, 5]}))
    assert ds.normalized(_saved(c, sid))["bild_versatz"] == {}


def _saved(c, sid):
    from backend.database.engine import session_scope
    from backend.models.entities import Datasheet

    with session_scope() as db:
        return db.get(Datasheet, sid).content


def test_multicolor_dot_and_colored_heading_suffix(admin_client):
    c = admin_client
    sid = _new(c, "LED Leuchtbalken", "Serie Spartan")
    content = _content(spez={"zeilen": [{"merkmal": "Spannungsbereich", "wert": "11-30V"}], "zusatz": "Tricolour",
                             "zusatz_farben": "gelb/klar/blau"},
                       bloecke=ds.empty_content()["bloecke"] + [{**ds.new_table("Bestellinformationen"), "zeilen": [
                           {"bild": None, "artnr": "RTSB182", "farbe": "gelb/blau/klar", "beschreibung": "x", "werte": []},
                           {"bild": None, "artnr": "RTSB183", "farbe": "gelb/lila", "beschreibung": "y", "werte": []}]}])
    html = _save(c, sid, content).json()["html"]
    # Zusatz in drei Farben: TRI | COL | OUR
    assert '<b class="tc"><span class="tc-gelb">Tri</span><span class="tc-klar">col</span><span class="tc-blau">our</span></b>' in html
    assert html.count('class="color-dot"') == 1 and html.count("<path ") == 3  # Tortenstücke; ungültige Farbe leer
    assert "style=" not in html
    editor = c.get(f"/datenblatt/{sid}").text
    assert 'value="gelb/blau/klar" selected' in editor and 'value="Tricolour"' in editor


def test_images_can_be_resized_and_lead_split(admin_client):
    """Bildgröße per Ziehen: in Prozent gespeichert (30–300, 100 = weg), nur für vorhandene Bilder; Aufteilung
    Text/Bilder im Kopfbereich; Seitenaufteilung rechnet mit der Größe."""
    c = admin_client
    sid = _new(c)
    a, b, d = (_upload(c, sid).json()["name"] for _ in range(3))
    ka, kb, kd = ds.image_key(a), ds.image_key(b), ds.image_key(d)
    block = {**ds.new_image_block(), "bild": d}
    r = _save(c, sid, _content(bilder_oben=[a], zeichnungen=[b], aufteilung="bild",
                               bloecke=[*ds.DEFAULT_BLOCKS, block],
                               bild_groesse={ka: 151.6, kb: 100, kd: 999, "fremd": 50}))
    assert r.status_code == 200
    html = r.json()["html"]
    assert f'data-size="{ka}"' in html and f'data-size="{kb}"' in html and f'data-size="{kd}"' in html  # Editor: greifbar
    assert 'data-scale="1.52"' in html and 'data-scale="3.0"' in html and "style=" not in html
    assert 'class="part lead split-bild"' in html
    saved = ds.normalized(_saved(c, sid))
    assert saved["bild_groesse"] == {ka: 152, kd: 300} and saved["aufteilung"] == "bild"
    page = c.get(f"/datenblatt/{sid}/vorschau").text
    assert 'data-scale="1.52"' in page and "data-size" not in page  # Druck: skaliert, nicht greifbar
    # ungültige Aufteilung -> Standard; entferntes Bild -> Größe verschwindet
    _save(c, sid, _content(bilder_oben=[a], aufteilung="quer", bild_groesse={ka: 20, kb: 150}))
    saved = ds.normalized(_saved(c, sid))
    assert saved["bild_groesse"] == {ka: 30} and saved["aufteilung"] == "normal"


def test_paginate_counts_scaled_images():
    name = "a" * 16 + ".jpg"
    blocks = [{**ds.new_image_block(), "bild": name} for _ in range(3)]  # je 45 mm: passt auf eine Seite
    content = _content(bloecke=blocks)
    assert len(ds.paginate(content)) == 1
    assert len(ds.paginate(dict(content, bild_groesse={"a" * 16: 300}))) == 3  # je 135 mm: eine Seite pro Bild


def test_several_group_images_in_one_table(admin_client):
    """Gruppenbild der Tabelle für die ersten Zeilen, ab einer Zeile ein anderes (links neben den folgenden Zeilen)."""
    c = admin_client
    sid = _new(c)
    a, b = _upload(c, sid).json()["name"], _upload(c, sid).json()["name"]
    rows = [{"bild": None, "artnr": f"RO24{i}", "farbe": "rot", "beschreibung": f"LED-Lichtsignalgeber {i}", "werte": []}
            for i in range(9)]
    rows[3]["gruppe"] = b
    table = {**ds.new_table(), "titel": "Bestellinformationen", "bild": a, "bild_pos": "links", "zeilen": rows}
    r = _save(c, sid, _content(bloecke=[*ds.DEFAULT_BLOCKS, table]))
    html = r.json()["html"]
    assert re.findall(r'<td class="img" rowspan="(\d+)"><img src="[^"]+/bild/([^"]+)"', html) == [("3", a), ("6", b)]
    saved = ds.tables(_saved(c, sid))[0]["zeilen"]
    assert saved[3]["gruppe"] == b and saved[0]["gruppe"] is None
    # Bild ab Zeile entfernen -> eine Gruppe über alle Zeilen
    rows[3]["gruppe"] = None
    html = _save(c, sid, _content(bloecke=[*ds.DEFAULT_BLOCKS, {**table, "zeilen": rows}])).json()["html"]
    assert re.findall(r'<td class="img" rowspan="(\d+)">', html) == ["9"]


def test_group_split_over_pages_shows_image_again():
    rows = [{"bild": None, "artnr": f"N{i}", "farbe": "", "beschreibung": "x", "werte": []} for i in range(60)]
    rows[30]["gruppe"] = "b" * 16 + ".png"
    table = {**ds.new_table(), "titel": "T", "bild": "a" * 16 + ".png", "zeilen": rows}
    pages = ds.paginate(_content(bloecke=[table]))
    pieces = [t for p in pages for t in p["teile"] if t["typ"] == "tabelle"]
    assert len(pieces) >= 2
    for piece in pieces:
        assert piece["zeilen"][0]["gspan"] >= 1 and piece["zeilen"][0]["gbild"]  # jedes Teil beginnt mit Bild
        assert sum(r["gspan"] for r in piece["zeilen"]) == len(piece["zeilen"])


def test_release_makes_sheet_visible_to_everyone_read_only(admin_client, user_client):
    """Entwurf sieht nur der Besitzer; nach „Freigeben“ steht das Blatt in der gemeinsamen Liste für alle
    (ansehen, drucken, kopieren), bearbeiten und freigeben bleibt beim Besitzer bzw. Admin."""
    u, a = user_client, admin_client
    sid = _new(u, titel="LED Lichtsignalgeber", untertitel="200 mm")
    name = _upload(u, sid).json()["name"]
    table = {**ds.new_table(), "titel": "Bestellinformationen",
             "zeilen": [{"bild": None, "artnr": "RO2401-A-CW", "farbe": "rot", "beschreibung": "rot, 12 V DC", "werte": []}]}
    _save(u, sid, _content(kopf={"titel": "LED Lichtsignalgeber", "untertitel": "200 mm"}, bilder_oben=[name],
                           bloecke=[*ds.DEFAULT_BLOCKS, table]))
    # Entwurf: andere sehen nichts
    other_id = _new(a, titel="Admin Blatt")
    assert "LED Lichtsignalgeber" not in _shared(a.get("/datenblatt").text)  # Entwurf nicht in der gemeinsamen Liste
    assert a.get(f"/datenblatt/{sid}/vorschau").status_code == 200  # Admin sieht alles
    page = u.get("/datenblatt").text
    assert "Entwurf" in page and "Freigegebene Datenblätter" in page
    assert u.get(f"/datenblatt/{other_id}/vorschau").status_code == 404
    # Benutzer dürfen nicht freigeben (auch nicht ihre eigenen) – nur Admin und Marketing
    assert u.post(f"/datenblatt/{other_id}/freigeben", data={"csrf_token": u.csrf, "aktiv": "1"}).status_code == 403
    assert u.post(f"/datenblatt/{sid}/freigeben", data={"csrf_token": u.csrf, "aktiv": "1"}).status_code == 403
    assert "/freigeben" not in u.get("/datenblatt").text and "/freigeben" not in u.get(f"/datenblatt/{sid}").text
    # Admin-Blatt freigeben -> Benutzer sieht es in der gemeinsamen Liste, nur lesend
    r = a.post(f"/datenblatt/{other_id}/freigeben", data={"csrf_token": a.csrf, "aktiv": "1"}, follow_redirects=False)
    assert r.status_code == 303
    page = u.get("/datenblatt").text
    assert "Admin Blatt" in _shared(page) and "admin" in _shared(page)
    assert u.get(f"/datenblatt/{other_id}/vorschau").status_code == 200
    assert "← Bearbeiten" not in u.get(f"/datenblatt/{other_id}/vorschau").text
    r = u.get(f"/datenblatt/{other_id}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/vorschau")  # Editor nur für Besitzer
    assert _save(u, other_id, _content()).status_code == 404  # nicht bearbeitbar
    copy_ = u.post(f"/datenblatt/{other_id}/kopieren", data={"csrf_token": u.csrf}, follow_redirects=False)
    assert copy_.status_code == 303  # kopieren geht (wird eigener Entwurf)
    # Admin gibt das Blatt des Benutzers frei: Bild für alle sichtbar, Suche nach Artikelnummer
    a.post(f"/datenblatt/{sid}/freigeben", data={"csrf_token": a.csrf, "aktiv": "1"})
    assert a.get(f"/datenblatt/{sid}/bild/{name}").status_code == 200
    assert "LED Lichtsignalgeber" in _shared(a.get("/datenblatt?q=ro 2401a").text)
    assert "LED Lichtsignalgeber" not in _shared(a.get("/datenblatt?q=XYZ999").text)
    # zurücknehmen -> wieder nur Besitzer
    a.post(f"/datenblatt/{other_id}/freigeben", data={"csrf_token": a.csrf})
    assert u.get(f"/datenblatt/{other_id}/vorschau").status_code == 404
    assert "Admin Blatt" not in _shared(u.get("/datenblatt").text)


def _shared(page: str) -> str:
    """Nur der Abschnitt „Freigegebene Datenblätter“ der Übersicht."""
    start = page.index('id="freigegeben"')
    return page[start:page.index("</section>", start)]


def test_marketing_role_releases_all_sheets_but_edits_only_own(app, admin_client, user_client):
    """Rolle Marketing: wie Benutzer, zusätzlich sieht sie alle Datenblätter und gibt sie frei (bzw. nimmt zurück)."""
    from fastapi.testclient import TestClient

    from backend.database.engine import session_scope
    from backend.models.entities import Datasheet, User
    from tests.conftest import login

    a, u = admin_client, user_client
    r = a.post("/benutzer", data={"csrf_token": a.csrf, "username": "marie", "password": "marketing-passwort-1",
                                  "role": "marketing"}, follow_redirects=False)
    assert r.status_code == 303 and 'value="marketing"' in a.get("/benutzer").text
    m = TestClient(app, base_url="https://testserver")
    m.csrf = login(m, "marie", "marketing-passwort-1")
    sid = _new(u, titel="Entwurf von Anna")
    page = m.get("/datenblatt").text
    assert "Entwurf von Anna" in page and "Alle Datenblätter" in page and f"/datenblatt/{sid}/freigeben" in page
    assert m.get(f"/datenblatt/{sid}/vorschau").status_code == 200
    assert "Freigeben" in m.get(f"/datenblatt/{sid}/vorschau").text  # Freigabe auch direkt aus der Vorschau
    assert m.get(f"/datenblatt/{sid}", follow_redirects=False).headers["location"].endswith("/vorschau")
    assert _save(m, sid, _content()).status_code == 404  # fremdes Blatt nicht bearbeiten
    assert m.get(f"/datenblatt/{sid}/loeschen").status_code == 404  # und nicht löschen
    assert m.get("/benutzer").status_code == 403  # sonst Rechte wie Benutzer
    m.post(f"/datenblatt/{sid}/freigeben", data={"csrf_token": m.csrf, "aktiv": "1"})
    with session_scope() as db:
        sheet = db.get(Datasheet, sid)
        marie = db.query(User).filter_by(username="marie").one()
        assert sheet.released_at and sheet.released_by == marie.id
        uid = db.query(User).filter_by(username="anna").one().id
    assert "Entwurf von Anna" in u.get("/datenblatt").text.split('id="freigegeben"')[1]
    # Rolle ändern: Admin kann einem Benutzer Marketing geben, sich selbst aber nicht die Admin-Rolle nehmen
    a.post(f"/benutzer/{uid}/rolle", data={"csrf_token": a.csrf, "role": "marketing"})
    with session_scope() as db:
        assert db.get(User, uid).role == "marketing"
        admin_id = db.query(User).filter_by(username="admin").one().id
    assert a.post(f"/benutzer/{admin_id}/rolle", data={"csrf_token": a.csrf, "role": "benutzer"}).status_code == 400


def test_editor_keeps_multiline_values_and_splits_bullets(user_client):
    """Mehrzeilige Werte (z. B. 12V/24V untereinander) stehen in Textfeldern, nicht in einzeiligen Eingaben – sonst
    gingen die Zeilenumbrüche beim nächsten automatischen Speichern verloren. Aufzählungspunkte (ohne Namen) stehen
    in einer eigenen Liste, Artikelzeilen in einer echten Tabelle mit Menü."""
    c = user_client
    sid = _new(c)
    props = [{"name": "Spannungsbereich", "wert": "12V: 10 bis 15V\n24V: 20 bis 30V", "sichtbar": True},
             {"name": "", "wert": "5 Jahre Garantie", "sichtbar": True}]
    table = {**ds.new_table(), "titel": "Bestellinformationen",
             "zeilen": [{"bild": None, "artnr": "RO2401", "farbe": "rot", "beschreibung": "rot", "werte": ["", ""]}]}
    assert _save(c, sid, _content(eigenschaften=props, bloecke=[*ds.DEFAULT_BLOCKS, table])).status_code == 200
    assert _saved(c, sid)["eigenschaften"][0]["wert"] == "12V: 10 bis 15V\n24V: 20 bis 30V"
    page = c.get(f"/datenblatt/{sid}").text
    assert re.search(r'<textarea class="prop-value" data-f="wert"[^>]*>12V: 10 bis 15V\n24V: 20 bis 30V</textarea>', page)
    named, bullets = page.split('data-list="eigenschaften"')[1].split('data-list="punkte"')
    assert "Spannungsbereich" in named and "5 Jahre Garantie" not in named
    assert "5 Jahre Garantie" in bullets.split("</div>\n    <button")[0]
    assert '<tbody data-sortable data-list="zeilen"><tr class="dse-trow"' in page and "data-insert-row" in page
    assert "data-undo" in page and "data-checklist" in page and "data-zoom" in page


def test_overview_search_covers_own_sheets_and_shows_counts(user_client):
    c = user_client
    page = c.get("/datenblatt").text
    assert "Erstes Datenblatt anlegen" in page and "data-open-dialog" not in page  # ohne Blätter: Formulare direkt
    sid = _new(c, titel="LED Lichtsignalgeber", untertitel="200 mm")
    _new(c, titel="Arbeitsscheinwerfer")
    table = {**ds.new_table(), "zeilen": [{"bild": None, "artnr": "RO2401-A", "farbe": "", "beschreibung": "x", "werte": []}]}
    _save(c, sid, _content(kopf={"titel": "LED Lichtsignalgeber", "untertitel": "200 mm"}, bloecke=[*ds.DEFAULT_BLOCKS, table]))
    page = c.get("/datenblatt").text
    assert 'data-open-dialog="neu-dialog"' in page and "1 Artikel" in page
    found = c.get("/datenblatt?q=ro2401a").text.split('id="freigegeben"')[0]
    assert "LED Lichtsignalgeber" in found and "Arbeitsscheinwerfer" not in found


def test_datasheet_job_page_uses_module_layout(admin_client, app):
    from tests.test_datasheet_import import _pdf

    c = admin_client
    r = c.post("/datenblatt/aus-pdf", data={"csrf_token": c.csrf},
               files={"datei": ("h.pdf", _pdf(), "application/pdf")}, follow_redirects=False)
    page = c.get(r.headers["location"]).text
    assert ">None<" not in page and ">wartet<" in page and "Liste einspielen" not in page  # kein Preislisten-Menü
    assert "öffnet sich automatisch" in page
