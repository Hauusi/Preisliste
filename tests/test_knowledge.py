"""Vertriebswissen: freie Eingabe mit Erkennung (ohne KI), einheitliche Schreibweise, gemeinsame Themen,
Folgen, private Einträge, Bearbeiten mit Name und Zeitpunkt, Angaben, Suche, Verknüpfungen."""

import re
from datetime import timedelta

from backend.database.engine import session_scope
from backend.models.entities import KbEntry, KbTopic, Manufacturer, User
from backend.services import knowledge as kb


def _topic(c, name, art="hersteller", aliase=""):
    r = c.post("/wissen/thema", data={"csrf_token": c.csrf, "art": art, "name": name, "aliase": aliase},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(re.search(r"/wissen/(\d+)", r.headers["location"]).group(1))


def _entry(c, text, **extra):
    data = {"csrf_token": c.csrf, "text": text, **extra}
    return c.post("/wissen/eintrag", data=data, follow_redirects=False)


def test_detect_and_tidy_without_ai():
    nordic = KbTopic(id=1, kind="hersteller", name="Nordic Lights", key="nordiclights", aliases=["Nordic"])
    balken = KbTopic(id=2, kind="gruppe", name="Leuchtbalken", key="leuchtbalken", aliases=["Lichtbalken"])
    adapter = KbTopic(id=3, kind="gruppe", name="Montageadapter", key="montageadapter", aliases=[])
    tops = [nordic, balken, adapter]
    assert kb.detect("nordic moq 36 stk", tops) == {"type": "bezug", "topic_ids": [1]}
    assert kb.detect("lichtbalken über 1,80 m mehr kalkulieren", tops)["type"] == "kalk"
    assert kb.detect("NORDIC-LIGHTS scheinwerfer brauchen immer den montageadapter", tops) == {
        "type": "pflicht", "topic_ids": [1, 3]}  # „montageadapter“ enthält „tage“ – trotzdem keine Lieferzeit
    assert kb.detect("lieferzeit 6 wochen", tops)["type"] == "liefer"
    assert kb.detect("nordiclightsfan", tops)["topic_ids"] == []  # nur ganze Wörter
    assert kb.tidy("  nordic moq 36 stk  ", tops) == "Nordic Lights Mindestbestellmenge 36 Stück."
    assert kb.tidy("lichtbalken über 1,80m mehr kalkulieren", tops) == "Lichtbalken über 1,80 m mehr kalkulieren."
    assert kb.tidy("braucht montageadapter , immer!", tops) == "Braucht Montageadapter, immer!"


def test_entry_flow_shared_edit_with_name_and_history(admin_client, user_client):
    a, u = admin_client, user_client
    nid = _topic(a, "Nordic Lights", aliase="Nordic")
    rid = _topic(a, "Riedfeld")
    r = _entry(u, "nordic unter 36 stk über riedfeld anfragen, andere kalkulation")
    assert r.status_code == 303 and r.headers["location"].startswith(f"/wissen/{nid}#e")
    with session_scope() as db:
        e = db.query(KbEntry).one()
        assert e.topic_ids == [nid, rid] and e.type == "kalk" and not e.private
        assert e.text == "Nordic Lights unter 36 Stück über Riedfeld anfragen, andere kalkulation."
        eid = e.id
    page = a.get(f"/wissen/{nid}").text  # für alle sichtbar
    assert "Nordic Lights unter 36 Stück über Riedfeld" in page and f'href="/wissen/{rid}"' in page
    assert "anna" in page and 'class="kb-graph"' in page  # Ersteller und Verknüpfung zu Riedfeld
    # Admin ändert den Eintrag von Anna: Name und Zeitpunkt stehen dabei, der alte Text im Verlauf
    r = a.post(f"/wissen/eintrag/{eid}", data={"csrf_token": a.csrf, "text": "unter 36 stück über riedfeld",
                                               "art": "bezug", "themen": [str(nid), str(rid)], "zurueck": str(nid)},
               follow_redirects=False)
    assert r.status_code == 303
    page = u.get(f"/wissen/{nid}").text
    assert "geändert von admin" in page and "vorher: Nordic Lights unter 36 Stück" in page
    assert "Unter 36 Stück über Riedfeld." in page
    with session_scope() as db:
        assert [c.action for c in kb.history(db, "eintrag", eid)] == ["geändert", "angelegt"]
    # Löschen nur mit Bestätigung, Verlauf bleibt
    assert u.post(f"/wissen/eintrag/{eid}/loeschen", data={"csrf_token": u.csrf}, follow_redirects=False).status_code == 303
    u.post(f"/wissen/eintrag/{eid}/loeschen", data={"csrf_token": u.csrf, "bestaetigt": "ja"})
    with session_scope() as db:
        assert db.query(KbEntry).count() == 0
        assert kb.history(db, "eintrag", eid)[0].action == "gelöscht"


def test_entry_needs_topic_and_uses_open_profile(user_client):
    c = user_client
    r = _entry(c, "irgendwas ohne hersteller")
    assert r.status_code == 303 and "fehler=" in r.headers["location"]
    gid = _topic(c, "Leuchtbalken", art="gruppe")
    r = _entry(c, "über 1,80 m mehr kalkulieren", vorgabe=str(gid))  # im Steckbrief: gehört dorthin
    assert r.status_code == 303 and r.headers["location"].startswith(f"/wissen/{gid}#e")
    with session_scope() as db:
        assert db.query(KbEntry).one().type == "kalk"
    nid = _topic(c, "Nordic Lights")
    r = _entry(c, "nordic lights lieferzeit 6 wochen", vorgabe=str(gid))  # erkannt: gehört zu Nordic, nicht zum Steckbrief
    assert r.headers["location"].startswith(f"/wissen/{nid}#e")
    assert "geändert von" not in c.get(f"/wissen/{nid}").text  # neu: noch nicht geändert


def test_private_entries_and_follow(admin_client, user_client):
    a, u = admin_client, user_client
    nid = _topic(a, "Nordic Lights")
    _entry(a, "Nordic Lights: meine eigene Notiz", privat="1")
    _entry(a, "Nordic Lights liefert in 6 Wochen")
    page = u.get(f"/wissen/{nid}").text
    assert "meine eigene Notiz" not in page and "liefert in 6 Wochen" in page
    with session_scope() as db:
        private_id = db.query(KbEntry).filter_by(private=True).one().id
    assert u.get(f"/wissen/eintrag/{private_id}/loeschen").status_code == 404  # fremd und privat: wie nicht vorhanden
    assert "meine eigene Notiz" in a.get(f"/wissen/{nid}").text
    # nicht mehr folgen: verschwindet aus Übersicht und Suche, bleibt für andere
    assert "Wochen" in u.get("/api/wissen/suche?q=wochen").text
    u.post(f"/wissen/{nid}/folgen", data={"csrf_token": u.csrf})
    assert u.get("/api/wissen/suche?q=wochen").json()["treffer"] == []
    assert "liefert in 6 Wochen" not in u.get("/wissen").text
    assert a.get("/api/wissen/suche?q=wochen").json()["treffer"]
    u.post(f"/wissen/{nid}/folgen", data={"csrf_token": u.csrf, "aktiv": "1"})
    assert u.get("/api/wissen/suche?q=wochen").json()["treffer"]


def test_facts_with_name_time_and_removal(admin_client, user_client):
    a, u = admin_client, user_client
    nid = _topic(a, "Nordic Lights")
    u.post(f"/wissen/{nid}/angabe", data={"csrf_token": u.csrf, "bezeichnung": "Mindestbestellmenge", "wert": "36 Stück"})
    page = a.get(f"/wissen/{nid}").text
    assert "<b>36 Stück</b>" in page and "anna," in page
    fid = re.search(r'name="id" value="(\d+)"', page).group(1)
    a.post(f"/wissen/{nid}/angabe", data={"csrf_token": a.csrf, "id": fid, "bezeichnung": "Mindestbestellmenge", "wert": "24 Stück"})
    page = u.get(f"/wissen/{nid}").text
    assert "<b>24 Stück</b>" in page and "Mindestbestellmenge: 36 Stück" not in page.split('id="angaben"')[1].split("</section>")[0]
    assert "Angabe geändert: Mindestbestellmenge: 24 Stück" in page  # Verlauf
    a.post(f"/wissen/{nid}/angabe", data={"csrf_token": a.csrf, "id": fid, "bezeichnung": "Mindestbestellmenge", "wert": ""})
    assert "<b>24 Stück</b>" not in u.get(f"/wissen/{nid}").text


def test_shared_manufacturer_list_from_price_lists(admin_client, user_client):
    """Hersteller aus den Preislisten aller Benutzer erscheinen einmal in der gemeinsamen Liste; im Steckbrief steht
    der eigene Preislisten-Hersteller."""
    with session_scope() as db:
        anna = db.query(User).filter_by(username="anna").one()
        admin = db.query(User).filter_by(username="admin").one()
        db.add(Manufacturer(owner_id=anna.id, name="Nordic Lights", code="NL", aliases=["Nordic"]))
        db.add(Manufacturer(owner_id=admin.id, name="nordic-lights", code="NO"))
        db.add(Manufacturer(owner_id=admin.id, name="Hella", code="HE"))
    page = user_client.get("/wissen").text
    assert page.count(">Nordic Lights</b>") == 1 and ">Hella</b>" in page
    with session_scope() as db:
        t = db.query(KbTopic).filter_by(key="nordiclights").one()
        assert t.aliases == ["Nordic"]
        tid, mid = t.id, db.query(Manufacturer).filter_by(code="NL").one().id
    page = user_client.get(f"/wissen/{tid}").text
    assert f'href="/hersteller/{mid}">Nordic Lights (NL)' in page


def test_stale_entries_and_check(admin_client):
    a = admin_client
    nid = _topic(a, "Nordic Lights")
    _entry(a, "Nordic Lights kein Lagerartikel")
    with session_scope() as db:
        e = db.query(KbEntry).one()
        e.checked_at = e.checked_at - timedelta(days=400)
        eid = e.id
    page = a.get("/wissen").text
    assert "Bitte prüfen" in page and "nicht geprüft" in page
    a.post(f"/wissen/eintrag/{eid}/geprueft", data={"csrf_token": a.csrf, "zurueck": str(nid)})
    assert "Bitte prüfen" not in a.get("/wissen").text


def test_suggest_endpoint_and_portal_tile(user_client):
    c = user_client
    nid = _topic(c, "Nordic Lights", aliase="Nordic")
    r = c.post("/wissen/vorschlag", json={"text": "nordic moq 36 stk"}, headers={"X-CSRF-Token": c.csrf})
    assert r.json() == {"art": "bezug", "themen": [nid], "text": "Nordic Lights Mindestbestellmenge 36 Stück."}
    assert c.post("/wissen/vorschlag", json={"text": "x"}).status_code == 403  # ohne Token
    _entry(c, "nordic moq 36 stk")
    home = c.get("/").text
    assert 'href="/wissen"' in home and "1 Eintrag" in home and "<h2>Vertriebswissen</h2>" in home
    assert "Mindestbestellmenge 36 Stück" in c.get("/wissen/suche?q=moq").text  # Suche findet auch das Eingetippte


def test_clear_data_keeps_shared_knowledge_of_deleted_users(admin_client, user_client, settings, app):
    from backend.cli import clear_data

    nid = _topic(user_client, "Nordic Lights")
    _entry(user_client, "Nordic Lights Mindestbestellmenge 36 Stück")
    _entry(user_client, "Nordic Lights meine Notiz", privat="1")
    user_client.post(f"/wissen/{nid}/folgen", data={"csrf_token": user_client.csrf})
    clear_data(settings, everything=True)
    with session_scope() as db:
        rows = db.query(KbEntry).all()
        assert [e.text for e in rows] == ["Nordic Lights Mindestbestellmenge 36 Stück."] and rows[0].author_id is None
    assert "Mindestbestellmenge 36 Stück" in admin_client.get(f"/wissen/{nid}").text
