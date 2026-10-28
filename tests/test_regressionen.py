"""Regressionstests für gefundene Fehler (Prüfung Oktober 2026)."""

import re

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import Article, PriceList, PriceUpdate
from backend.services import datasheets as ds
from tests.test_datasheets import PNG, _new, _step
from tests.test_price_update import _import, _ours, _setup


def _abgleich(c, app, tmp_path, mid):
    _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"], ["A1", "a", "10,50"], ["A2", "b", "7,00"]],
            mid, "HERSTELLER")
    return c.post(f"/hersteller/{mid}/abgleich", data={"csrf_token": c.csrf}, follow_redirects=False).headers["location"]


def test_calc_without_rule_shows_form_instead_of_server_error(admin_client, tmp_path, app):
    c = admin_client
    mid, _ = _setup(c)
    lid = _ours(c, app, tmp_path, mid, [["A1", "x", "10,00", "20,00"]])
    r = c.post(f"/listen/{lid}/kalkulation", data={"csrf_token": c.csrf, "rule_id": "", "quantity": "1"})
    assert r.status_code == 400 and "Regel wählen und Menge &gt; 0 angeben" in r.text


def test_new_articles_added_during_open_abgleich_survive_adoption(admin_client, tmp_path, app):
    c = admin_client
    mid, _ = _setup(c)
    _ours(c, app, tmp_path, mid, [["A1", "x", "10,00", "20,00"]])
    url = _abgleich(c, app, tmp_path, mid)
    r = c.post("/neue-artikel/aufnehmen", data={"csrf_token": c.csrf, "text": "RAA2", "line": "1", "bestaetigt": "ja"})
    assert r.status_code == 200
    c.post(url + "/alle-bestaetigen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    c.post(url + "/uebernehmen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    with session_scope() as db:
        upd = db.scalars(select(PriceUpdate)).all()[-1]
        arts = {a.article_number: {p.price_type: p.amount for p in a.prices}
                for a in db.scalars(select(Article).where(Article.price_list_id == upd.adopted_list_id))}
        pl = db.get(PriceList, upd.adopted_list_id)
        assert set(arts) == {"A1", "A2"}
        assert arts["A2"] == {"EK": 7, "LISTE": 14}  # EK 7,00 aus der Herstellerliste × 2
        assert pl.summary["articles"] == 2 and pl.summary["nachtraeglich_aufgenommen"] == 1


def test_admin_adopting_users_abgleich_keeps_list_with_user(admin_client, user_client, tmp_path, app):
    c = user_client
    mid, _ = _setup(c)
    _ours(c, app, tmp_path, mid, [["A1", "x", "10,00", "20,00"]])
    url = _abgleich(c, app, tmp_path, mid)
    a = admin_client
    a.post(url + "/alle-bestaetigen", data={"csrf_token": a.csrf, "bestaetigt": "ja"})
    a.post(url + "/uebernehmen", data={"csrf_token": a.csrf, "bestaetigt": "ja"})
    adopted = int(re.search(r'href="/listen/(\d+)">Neue aktuelle Liste', c.get(url).text).group(1))
    assert c.get(f"/listen/{adopted}").status_code == 200
    from backend.models.entities import Manufacturer
    from backend.services.updates import current_list

    with session_scope() as db:
        assert current_list(db, db.get(Manufacturer, mid)).id == adopted


def test_clear_data_alles_removes_datasheets_of_deleted_users(user_client, admin_client, settings, app):
    from backend.cli import clear_data

    sid = _new(user_client)
    _step(user_client, sid, "bilder", {}, files={"bild_0": ("a.png", PNG, "image/png")})
    keep = _new(admin_client, "Admin-Blatt", "")
    _, counts = clear_data(settings, everything=True)
    assert counts["Datenblätter (der gelöschten Benutzer)"] == 1
    assert not ds.image_dir(settings, sid).exists()
    assert "Admin-Blatt" in admin_client.get("/datenblatt").text and keep


def test_reset_data_removes_datasheet_images(user_client, settings, app):
    from backend.cli import reset_data

    sid = _new(user_client)
    _step(user_client, sid, "bilder", {}, files={"bild_0": ("a.png", PNG, "image/png")})
    reset_data(settings)
    assert not (settings.upload_dir / "datenblatt").exists()
