"""Datenblatt erstellen: Schritt-für-Schritt-Eingabe, Bilder, Seitenaufteilung, Sichtbarkeit."""

import base64
import re

from backend.services import datasheets as ds

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _new(c, titel="LED Blitzmodule", untertitel="Serie Gecko") -> int:
    r = c.post("/datenblatt/neu", data={"csrf_token": c.csrf, "titel": titel, "untertitel": untertitel},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/schritt/beschreibung")
    return int(re.search(r"/datenblatt/(\d+)/", r.headers["location"]).group(1))


def _step(c, sid, step, data, files=None, aktion="weiter"):
    return c.post(f"/datenblatt/{sid}/schritt/{step}", data={"csrf_token": c.csrf, "aktion": aktion, **data},
                  files=files, follow_redirects=False)


def test_portal_tile_opens_datasheet_module(admin_client):
    page = admin_client.get("/").text
    assert 'href="/datenblatt"' in page and "0 Datenblätter" in page
    assert "Noch keine Datenblätter" in admin_client.get("/datenblatt").text


def test_full_wizard_and_print_layout(admin_client, settings):
    c = admin_client
    sid = _new(c)
    r = _step(c, sid, "beschreibung", {"text": "Flaches Design.\n\nIP69k dicht.", "punkte": "2 Jahre Garantie\n• Synchronisierbar\n"})
    assert r.headers["location"] == f"/datenblatt/{sid}/schritt/bilder"
    r = _step(c, sid, "bilder", {}, files={"bild_0": ("produkt.png", PNG, "image/png")})
    assert r.status_code == 303
    r = _step(c, sid, "spez", {"merkmal_0": "Spannungsbereich", "wert_0": "11-30V", "merkmal_1": "Abmessungen",
                               "wert_1": "74 x 24 x 18mm (Gecko 3)\n123 x 24 x 18mm (Gecko 6)", "merkmal_2": "", "wert_2": ""},
              files={"zeichen_0": ("ece.png", PNG, "image/png")})
    assert r.status_code == 303
    r = _step(c, sid, "artikel", {
        "g0_titel": "Gecko 3 - Horizontale Montage", "g0_spalte0": "Zulassung", "g0_spalte1": "Montage", "g0_spalte2": "",
        "g0_r0_artnr": "RTG3HSA0CB", "g0_r0_farbe": "gelb", "g0_r0_beschreibung": "LED Blitzmodul Gecko 3, 11-30V, gelb",
        "g0_r0_w0": "ECE-R65 Klasse I", "g0_r0_w1": "Horizontal",
        "g0_r1_artnr": "", "g0_r1_beschreibung": "",
        "g0_einfuegen": "RTG3HSB0CB\tLED Blitzmodul Gecko 3, 11-30V, blau\tECE-R65 Klasse I\tHorizontal\n"
                        "RTG3HSW0CB;LED Blitzmodul Gecko 3, 11-30V, klar;ECE-R65 Klasse I;Horizontal",
    }, files={"g0_bild": ("g3.png", PNG, "image/png")})
    assert r.status_code == 303
    r = _step(c, sid, "zubehoer", {"z0_artnr": "RTSP_G3BK1", "z0_beschreibung": "90° Winkel für Gecko 3",
                                   "z1_artnr": "", "z1_beschreibung": ""},
              files={"z0_bild": ("w.png", PNG, "image/png")})
    assert r.status_code == 303
    r = _step(c, sid, "fuss", {"version": "18102022"}, aktion="fertig")
    assert r.headers["location"] == f"/datenblatt/{sid}/vorschau"

    page = c.get(f"/datenblatt/{sid}/vorschau").text
    assert page.count('class="page"') == 3  # Startseite, Artikel, Zubehör
    assert "<h1>LED Blitzmodule</h1>" in page and "Serie Gecko" in page
    assert "<p>Flaches Design.</p>" in page and "<li>Synchronisierbar</li>" in page
    assert "Spannungsbereich:" in page and "74 x 24 x 18mm (Gecko 3)<br>123 x 24 x 18mm (Gecko 6)" in page
    assert page.count('class="color ') == 3 and 'class="color blau"' in page and 'class="color klar"' in page
    assert "RTG3HSW0CB" in page and "Horizontal" in page and "RTSP_G3BK1" in page
    assert "Braun &amp; Braun GmbH" in page and "Version 18102022" in page

    # Bilder liegen beim Datenblatt und sind nur angemeldet abrufbar
    names = re.findall(rf"/datenblatt/{sid}/bild/([0-9a-f]{{16}}\.png)", page)
    assert len(set(names)) == 4
    img = c.get(f"/datenblatt/{sid}/bild/{names[0]}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == PNG
    assert len(list(ds.image_dir(settings, sid).iterdir())) == 4


def test_invalid_image_rejected_and_replaced_images_removed(admin_client, settings):
    c = admin_client
    sid = _new(c)
    r = _step(c, sid, "bilder", {}, files={"bild_0": ("boese.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert r.status_code == 400 and "ist kein Bild" in r.text
    _step(c, sid, "bilder", {}, files={"bild_0": ("a.png", PNG, "image/png")})
    first = list(ds.image_dir(settings, sid).iterdir())
    assert len(first) == 1
    _step(c, sid, "bilder", {}, files={"bild_0": ("b.png", PNG, "image/png")})
    second = list(ds.image_dir(settings, sid).iterdir())
    assert len(second) == 1 and second[0].name != first[0].name
    _step(c, sid, "bilder", {"bild_0_weg": "ja"})
    assert list(ds.image_dir(settings, sid).iterdir()) == []
    assert c.get(f"/datenblatt/{sid}/bild/..%2F..%2Fpreisliste.sqlite3").status_code == 404


def test_title_required_and_navigation(admin_client):
    c = admin_client
    r = c.post("/datenblatt/neu", data={"csrf_token": c.csrf, "titel": " "}, follow_redirects=False)
    assert r.status_code == 400 and "Titel" in r.text
    sid = _new(c)
    assert _step(c, sid, "beschreibung", {"text": "x"}, aktion="zurueck").headers["location"].endswith("/schritt/kopf")
    assert _step(c, sid, "beschreibung", {"text": "x"}, aktion="gehe:zubehoer").headers["location"].endswith("/schritt/zubehoer")
    r = _step(c, sid, "kopf", {"titel": "", "untertitel": "neu"})
    assert r.status_code == 400
    assert "LED Blitzmodule" in c.get("/datenblatt").text  # alter Titel bleibt
    assert c.get(f"/datenblatt/{sid}/schritt/unbekannt").status_code == 404


def test_add_group_and_remove_group(admin_client):
    c = admin_client
    sid = _new(c)
    r = _step(c, sid, "artikel", {"g0_titel": "Gruppe A", "g0_spalte0": "Zulassung", "g0_r0_artnr": "A1",
                                  "g0_r0_beschreibung": "x"}, aktion="gruppe")
    assert r.headers["location"].endswith("/schritt/artikel#neu")
    page = c.get(f"/datenblatt/{sid}/schritt/artikel").text
    assert 'name="g1_titel"' in page and 'value="Gruppe A"' in page
    _step(c, sid, "artikel", {"g0_titel": "Gruppe A", "g0_weg": "ja", "g1_titel": "Gruppe B", "g1_r0_artnr": "B1"})
    page = c.get(f"/datenblatt/{sid}/vorschau").text
    assert "Gruppe B" in page and "Gruppe A" not in page


def test_copy_delete_and_user_isolation(admin_client, user_client, settings):
    sid = _new(user_client, "Arbeitsscheinwerfer", "Serie X")
    _step(user_client, sid, "bilder", {}, files={"bild_0": ("a.png", PNG, "image/png")})
    # Andere Benutzer sehen fremde Datenblätter nicht, Admin sieht alles
    other = _new(admin_client, "Admin-Blatt", "")
    assert user_client.get(f"/datenblatt/{other}/vorschau").status_code == 404
    assert "Admin-Blatt" not in user_client.get("/datenblatt").text
    assert "Arbeitsscheinwerfer" in admin_client.get("/datenblatt").text

    r = user_client.post(f"/datenblatt/{sid}/kopieren", data={"csrf_token": user_client.csrf}, follow_redirects=False)
    copy_id = int(re.search(r"/datenblatt/(\d+)/", r.headers["location"]).group(1))
    assert len(list(ds.image_dir(settings, copy_id).iterdir())) == 1
    assert "Arbeitsscheinwerfer – Serie X (Kopie)" in user_client.get("/datenblatt").text

    r = user_client.post(f"/datenblatt/{sid}/loeschen", data={"csrf_token": user_client.csrf, "bestaetigt": "ja"},
                         follow_redirects=False)
    assert r.status_code == 303
    assert not ds.image_dir(settings, sid).exists()
    assert user_client.get(f"/datenblatt/{sid}/vorschau").status_code == 404
    assert ds.image_dir(settings, copy_id).exists()


def test_paginate_splits_long_groups_and_accessories():
    c = ds.empty_content()
    rows = [{"artnr": f"A{i}", "farbe": "", "beschreibung": "x", "werte": []} for i in range(50)]
    c["gruppen"] = [{"titel": "Klein", "bild": None, "spalten": [], "zeilen": rows[:3]},
                    {"titel": "Gross", "bild": None, "spalten": [], "zeilen": rows}]
    c["zubehoer"] = [{"artnr": f"Z{i}", "beschreibung": "", "bild": None} for i in range(15)]
    pages = ds.paginate(c)
    arts = [p for p in pages if p["art"] == "artikel"]
    assert pages[0]["art"] == "artikel"  # ohne Beschreibung/Spezifikation keine Startseite
    shown = [r["artnr"] for p in arts for g in p["gruppen"] if g["titel"] == "Gross" for r in g["zeilen"]]
    assert shown == [r["artnr"] for r in rows]  # keine Zeile verloren, Reihenfolge bleibt
    assert any(g["fortsetzung"] for p in arts for g in p["gruppen"])
    acc = [p for p in pages if p["art"] == "zubehoer"]
    assert len(acc) == 2 and sum(len(p["zeilen"]) for p in acc) == 15 and acc[1]["fortsetzung"]
    for p in arts:  # geschätzte Höhe jeder Seite passt
        assert sum(ds._group_mm(g["zeilen"]) for g in p["gruppen"]) <= ds.PAGE_BODY_MM + ds.GROUP_GAP_MM


def test_guess_color_from_description():
    assert ds.guess_color("LED Blitzmodul Gecko 3, 11-30V, gelb") == "gelb"
    assert ds.guess_color("Blitzer, blau/weiß") == "weiss"
    assert ds.guess_color("Winkel für Gecko 3") == ""
