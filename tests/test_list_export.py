"""Gespeicherte Listen jederzeit als Excel herunterladen (auch die nach dem Abgleich übernommene Liste)."""

import io
import re

import openpyxl

from tests.test_price_update import _import, _ours, _setup


def _sheet(data: bytes, name="Preisliste"):
    return [list(r) for r in openpyxl.load_workbook(io.BytesIO(data))[name].iter_rows(values_only=True)]


def test_adopted_list_can_be_downloaded_later(admin_client, user_client, tmp_path, app):
    c = admin_client
    mid, _ = _setup(c)
    _ours(c, app, tmp_path, mid, [["LED1", "Leuchte a", "10,00", "20,00"], ["LED2", "Leuchte b", "5,00", "10,00"]])
    _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"], ["LED1", "a", "12,00"]], mid, "HERSTELLER")
    url = c.post(f"/hersteller/{mid}/abgleich", data={"csrf_token": c.csrf}, follow_redirects=False).headers["location"]
    c.post(url + "/alle-bestaetigen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    c.post(url + "/uebernehmen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    adopted = int(re.search(r'href="/listen/(\d+)">Neue aktuelle Liste', c.get(url).text).group(1))

    page = c.get(f"/listen/{adopted}").text
    assert f'href="/listen/{adopted}/export"' in page and "Als Excel herunterladen" in page
    assert f'href="/listen/{adopted}/export"' in c.get("/listen").text

    r = c.get(f"/listen/{adopted}/export")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('.xlsx"')
    rows = _sheet(r.content)
    assert rows[0][:6] == ["Artikelnummer", "Original-Nr.", "Hersteller", "Bezeichnung", "Kategorie", "Einheit"]
    assert "EK" in rows[0] and "VK" in rows[0] and "Marge %" in rows[0]
    ek, vk = rows[0].index("EK"), rows[0].index("VK")
    by_nr = {row[0]: row for row in rows[1:]}
    assert by_nr["RALED1"][ek] == 12 and by_nr["RALED1"][vk] == 24  # neuer EK × 2
    assert by_nr["RALED2"][ek] == 5 and by_nr["RALED2"][vk] == 10

    # fremde Listen nicht abrufbar
    assert user_client.get(f"/listen/{adopted}/export").status_code == 404
