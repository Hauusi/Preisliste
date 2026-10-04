"""Dashboard: Aufgaben, Kennzahlen und Herstellerkacheln."""

from tests.test_annual_extras import _start
from tests.test_price_update import _import, _ours, _setup


def test_dashboard_shows_tasks_and_manufacturer_status(admin_client, tmp_path, app):
    c = admin_client
    page = c.get("/").text
    assert "So funktioniert" in page and "Noch keine Hersteller" in page
    mid, rule_id = _setup(c)
    ours = _ours(c, app, tmp_path, mid, [["LED1", "a", "10,00", "20,00"], ["LED2", "b", "10,00", "20,00"]])
    new = _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"], ["LED1", "a", "12,00"]],
                  mid, "HERSTELLER")
    page = c.get("/").text
    assert "neue Herstellerliste noch nicht abgeglichen" in page and f"/listen/{new}/kalkulation" in page
    url = _start(c, ours, new, rule_id)
    page = c.get("/").text
    assert "Jahresabgleich: 2 Positionen zu prüfen" in page and "2 offen" in page
    assert "+20 %" in page  # Ø EK-Änderung
    c.post(url + "/alle-bestaetigen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    page = c.get("/").text
    assert "Abgleich geprüft – noch nicht übernommen" in page
    c.post(url + "/uebernehmen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    page = c.get("/").text
    assert "übernommen" in page and "Alles erledigt" in page
