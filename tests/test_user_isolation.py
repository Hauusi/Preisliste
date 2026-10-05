"""Jeder Benutzer sieht nur seine eigenen Hersteller, Regeln, Listen, Abgleiche und Vergleiche; Admin sieht alles."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth.core import create_user
from backend.config import get_settings
from backend.database.engine import session_scope
from backend.models.entities import Manufacturer, PriceList, Rule
from tests.conftest import login
from tests.test_price_update import _import

PW = "berta-passwort-123"


@pytest.fixture
def berta(app):
    with session_scope() as db:
        create_user(db, "berta", PW, "benutzer", app.dependency_overrides[get_settings]())
    c = TestClient(app, base_url="https://testserver")
    c.csrf = login(c, "berta", PW)
    return c


def _world(c, app, tmp_path, tag, name, code, factor):
    """Hersteller mit Regel, unsere Liste, Herstellerliste und Abgleich für einen Benutzer."""
    r = c.post("/hersteller", data={"csrf_token": c.csrf, "name": name, "code": code}, follow_redirects=False)
    assert r.status_code == 303, r.text
    mid = int(r.headers["location"].split("?")[0].rsplit("/", 1)[1])
    r = c.post("/regeln/neu", data={"csrf_token": c.csrf, "name": f"Regel {tag}", "manufacturer_id": str(mid),
                                    "start_price": "EK", "rounding_mode": "HALF_UP", "rounding_places": "2",
                                    "rounding_timing": "STEP", "step_1_type": "multiply", "step_1_value": factor},
               follow_redirects=False)
    rid = r.headers["location"].rsplit("/", 1)[1]
    ours = _import(c, app, tmp_path, f"ours_{tag}", [["Artikelnummer", "Bezeichnung", "EK", "VK"],
                                                     [f"{tag}1", f"Artikel {tag}", "10,00", "20,00"]],
                   mid, "UNSERE", ("supplier_price", "list_price"))
    new = _import(c, app, tmp_path, f"new_{tag}", [["Artikelnummer", "Bezeichnung", "EK"],
                                                   [f"{tag}1", f"Artikel {tag}", "11,00"]], mid, "HERSTELLER")
    r = c.post("/aktualisierungen", data={"csrf_token": c.csrf, "base_id": ours, "source_id": new,
                                          "rule_id": rid}, follow_redirects=False)
    assert r.status_code == 303, r.text
    r2 = c.post("/vergleiche", data={"csrf_token": c.csrf, "old_id": ours, "new_id": new, "price_type": "EK"},
                follow_redirects=False)
    assert r2.status_code == 303, r2.text
    return {"mid": mid, "rid": rid, "ours": ours, "new": new, "upd": r.headers["location"],
            "cmp": r2.headers["location"]}


def test_users_only_see_their_own_content(admin_client, user_client, berta, tmp_path, app):
    anna = _world(user_client, app, tmp_path, "IND", "Industrieleuchten", "IL", "2,6")
    # gleicher Herstellername und gleiches Kürzel bei einem anderen Benutzer erlaubt
    bert = _world(berta, app, tmp_path, "FZG", "Industrieleuchten", "IL", "3")
    with session_scope() as db:
        owners = {m.owner_id for m in db.scalars(select(Manufacturer))}
        assert len(owners) == 2
        assert {r.owner_id for r in db.scalars(select(Rule))} == owners

    def pages(c):
        return "".join(c.get(u).text for u in ("/", "/listen", "/hersteller", "/regeln", "/aktualisierungen",
                                               "/vergleiche"))

    a_pages, b_pages = pages(user_client), pages(berta)
    assert "ours_IND" in a_pages and "ours_FZG" not in a_pages and "Regel FZG" not in a_pages
    assert "ours_FZG" in b_pages and "ours_IND" not in b_pages and "Regel IND" not in b_pages

    # Direktzugriff auf fremde Inhalte: wie nicht vorhanden
    foreign = [f"/listen/{bert['ours']}", f"/listen/{bert['ours']}/kalkulation", f"/listen/{bert['ours']}/meldungen",
               f"/hersteller/{bert['mid']}", f"/regeln/{bert['rid']}", bert["upd"], bert["upd"] + "/export?entwurf=1",
               bert["cmp"], bert["cmp"] + "/export", f"/api/price-lists/{bert['ours']}/articles",
               f"/listen/{bert['ours']}/loeschen", f"/hersteller/{bert['mid']}/loeschen", f"/regeln/{bert['rid']}/loeschen"]
    for url in foreign:
        assert user_client.get(url).status_code == 404, url
    assert all(pl["name"].endswith("IND") for pl in user_client.get("/api/price-lists").json())

    # Schreiben auf fremde Inhalte ebenso abgelehnt
    c = user_client
    assert c.post("/hersteller", data={"csrf_token": c.csrf, "id": bert["mid"], "name": "X"}).status_code == 404
    assert c.post(bert["upd"] + "/alle-bestaetigen", data={"csrf_token": c.csrf, "bestaetigt": "ja"}).status_code == 404
    assert c.post(f"/listen/{bert['ours']}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"}).status_code == 404
    # fremde Listen/Regeln lassen sich nicht in eigene Abgleiche/Vergleiche einschleusen
    r = c.post("/aktualisierungen", data={"csrf_token": c.csrf, "base_id": anna["ours"], "source_id": bert["new"],
                                          "rule_id": anna["rid"]})
    assert r.status_code == 400
    r = c.post("/aktualisierungen", data={"csrf_token": c.csrf, "base_id": anna["ours"], "source_id": anna["new"],
                                          "rule_id": bert["rid"]})
    assert r.status_code == 400 and "Kalkulationsregel" in r.text
    r = c.post("/vergleiche", data={"csrf_token": c.csrf, "old_id": anna["ours"], "new_id": bert["new"],
                                    "price_type": "EK"})
    assert r.status_code == 400
    r = c.post("/regeln/neu", data={"csrf_token": c.csrf, "name": "X", "manufacturer_id": str(bert["mid"]),
                                    "start_price": "EK", "rounding_mode": "HALF_UP", "rounding_places": "2",
                                    "rounding_timing": "STEP", "step_1_type": "multiply", "step_1_value": "2"})
    assert r.status_code == 400 and "Hersteller nicht gefunden" in r.text

    # Neue Artikel: Kürzel IL wird nur unter den eigenen Herstellern gesucht
    page = c.post("/neue-artikel", data={"csrf_token": c.csrf, "text": "ILNEU1;Neu;5,00"}).text
    assert "1 von 1 Zeilen aufnehmbar" in page and "ours_IND" in page

    # Admin sieht alles, mit Benutzerspalte
    page = admin_client.get("/listen").text
    assert "ours_IND" in page and "ours_FZG" in page and "anna" in page and "berta" in page
    for url in (bert["upd"], f"/hersteller/{anna['mid']}", f"/regeln/{bert['rid']}"):
        assert admin_client.get(url).status_code == 200
    # Admin: gleiches Kürzel bei zwei Benutzern wird bei neuen Artikeln nicht geraten
    page = admin_client.post("/neue-artikel", data={"csrf_token": admin_client.csrf, "text": "ILNEU1"}).text
    assert "gibt es bei mehreren Benutzern" in page


def test_import_offers_only_own_manufacturers(user_client, berta, tmp_path, app):
    from tests.conftest import make_xlsx
    from tests.test_import_web import upload

    berta.post("/hersteller", data={"csrf_token": berta.csrf, "name": "Bertas Hersteller", "code": "BH"})
    user_client.post("/hersteller", data={"csrf_token": user_client.csrf, "name": "Annas Hersteller", "code": "AH"})
    r = upload(user_client, make_xlsx(tmp_path / "x.xlsx", [["Art", "Bez", "EK"], ["BH1", "x", "1,00"]]))
    list_id = int(r.headers["location"].rsplit("/", 1)[1])
    page = user_client.post(f"/import/{list_id}/spalten", data={
        "csrf_token": user_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "description", "col_2": "supplier_price"}).text
    assert "Annas Hersteller" in page and "Bertas Hersteller" not in page
    with session_scope() as db:
        bertas = db.scalar(select(Manufacturer).where(Manufacturer.name == "Bertas Hersteller"))
    r = user_client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": user_client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_2": "supplier_price", "manufacturer_id": str(bertas.id), "currency": "EUR"})
    assert r.status_code == 400 and "Hersteller nicht gefunden" in r.text
    # fremde Entwürfe sind nicht erreichbar
    assert berta.get(f"/import/{list_id}").status_code == 404
