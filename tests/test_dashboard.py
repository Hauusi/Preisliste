"""Dashboard: Aufgaben, Kennzahlen und Herstellerkacheln."""

from tests.test_annual_extras import _start
from tests.test_price_update import _import, _ours, _setup


def test_dashboard_shows_tasks_and_manufacturer_status(admin_client, tmp_path, app):
    c = admin_client
    page = c.get("/preisliste").text
    assert "So funktioniert" in page and "Noch keine Hersteller" in page
    mid, rule_id = _setup(c)
    ours = _ours(c, app, tmp_path, mid, [["LED1", "a", "10,00", "20,00"], ["LED2", "b", "10,00", "20,00"]])
    new = _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"], ["LED1", "a", "12,00"]],
                  mid, "HERSTELLER")
    page = c.get("/preisliste").text
    assert "neue Herstellerliste noch nicht abgeglichen" in page and f'action="/hersteller/{mid}/abgleich"' in page
    # Ein Klick auf „Abgleich starten“ startet unsere Liste gegen die neueste Herstellerliste
    r = c.post(f"/hersteller/{mid}/abgleich", data={"csrf_token": c.csrf}, follow_redirects=False)
    assert r.status_code == 303 and "/aktualisierungen/" in r.headers["location"]
    url = r.headers["location"]
    page = c.get("/preisliste").text
    assert "RaphiLED: 2 Positionen prüfen" in page and "2 offen" in page
    assert "+20 %" in page  # Ø EK-Änderung
    c.post(url + "/alle-bestaetigen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    page = c.get("/preisliste").text
    assert "RaphiLED: geprüft – jetzt abschließen" in page
    c.post(url + "/uebernehmen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    page = c.get("/preisliste").text
    assert "übernommen" in page and "Alles erledigt" in page
