from sqlalchemy import func, select

from backend.database.engine import session_scope
from backend.models.entities import Article, Comparison, Manufacturer, PriceList, Rule
from tests.test_group_b_web import RULE_FORM, import_list


def _two_lists(c, tmp_path):
    old = import_list(c, tmp_path, "alt", [["Art.-Nr.", "Bezeichnung", "Listenpreis"], ["A", "x", "1,00"]])
    new = import_list(c, tmp_path, "neu", [["Art.-Nr.", "Bezeichnung", "Listenpreis"], ["A", "x", "2,00"]])
    c.post("/vergleiche", data={"csrf_token": c.csrf, "old_id": old, "new_id": new, "price_type": "LISTE"})
    return old, new


def test_delete_price_list_requires_double_confirmation(admin_client, tmp_path, settings):
    c = admin_client
    old, new = _two_lists(c, tmp_path)
    assert 'href="/listen/%d/loeschen"' % old in c.get("/listen").text  # Papierkorb in der Liste
    page = c.get(f"/listen/{old}/loeschen").text
    assert "1 Artikel" in page and "1 Vergleich" in page and 'name="bestaetigt"' in page
    r = c.post(f"/listen/{old}/loeschen", data={"csrf_token": c.csrf})
    assert r.status_code == 400 and "Häkchen" in r.text
    with session_scope() as db:
        assert db.get(PriceList, old) is not None
    r = c.post(f"/listen/{old}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"}, follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as db:
        assert db.get(PriceList, old) is None
        assert db.scalar(select(func.count(Article.id)).where(Article.price_list_id == old)) == 0
        assert db.scalar(select(func.count(Comparison.id))) == 0
        assert db.get(PriceList, new) is not None
    assert len(list(settings.upload_dir.iterdir())) == 1  # nur die Datei der anderen Liste bleibt


def test_manufacturer_delete_blocked_while_used_then_allowed(admin_client, tmp_path):
    c = admin_client
    old, new = _two_lists(c, tmp_path)
    with session_scope() as db:
        mid = db.scalar(select(Manufacturer)).id
    page = c.get(f"/hersteller/{mid}/loeschen").text
    assert "zuerst diese Preislisten löschen" in page and 'name="bestaetigt"' not in page
    assert c.post(f"/hersteller/{mid}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"}).status_code == 400
    for lid in (old, new):
        c.post(f"/listen/{lid}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    r = c.post(f"/hersteller/{mid}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"}, follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as db:
        assert db.get(Manufacturer, mid) is None


def test_rule_delete_and_permissions(admin_client, user_client, tmp_path):
    c = admin_client
    r = c.post("/regeln/neu", data={**RULE_FORM, "csrf_token": c.csrf}, follow_redirects=False)
    rid = int(r.headers["location"].rsplit("/", 1)[1])
    assert f'href="/regeln/{rid}/loeschen"' in c.get("/regeln").text
    # fremde Regel: für andere Benutzer nicht vorhanden
    assert user_client.get(f"/regeln/{rid}/loeschen").status_code == 404
    assert f'href="/regeln/{rid}/loeschen"' not in user_client.get("/regeln").text
    c.post(f"/regeln/{rid}/loeschen", data={"csrf_token": c.csrf, "bestaetigt": "ja"})
    with session_scope() as db:
        assert db.get(Rule, rid).deleted


def test_user_cannot_delete_foreign_list(admin_client, user_client, tmp_path):
    old, _ = _two_lists(admin_client, tmp_path)
    assert user_client.get(f"/listen/{old}/loeschen").status_code == 404
    assert user_client.post(f"/listen/{old}/loeschen",
                            data={"csrf_token": user_client.csrf, "bestaetigt": "ja"}).status_code == 404
