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
        assert e.text == "Nordic Lights unter 36 Stück über Riedfeld anfragen, andere Kalkulation."
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
    assert page.count("<span>Nordic Lights</span>") == 1 and "<span>Hella</span>" in page
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
    assert "Bitte prüfen" in page and "Prüffrist abgelaufen" in page
    a.post(f"/wissen/eintrag/{eid}/geprueft", data={"csrf_token": a.csrf, "zurueck": str(nid)})
    assert "Bitte prüfen" not in a.get("/wissen").text


def test_suggest_endpoint_and_portal_tile(user_client):
    c = user_client
    nid = _topic(c, "Nordic Lights", aliase="Nordic")
    r = c.post("/wissen/vorschlag", json={"text": "nordic moq 36 stk"}, headers={"X-CSRF-Token": c.csrf})
    assert r.json() == {"art": "bezug", "themen": [nid], "text": "Nordic Lights Mindestbestellmenge 36 Stück.",
                        "angaben": [{"field": "moq", "value": "36", "label": "Mindestbestellmenge 36 Stück"}]}
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



def _field(c, tid, field, **data):
    return c.post(f"/wissen/{tid}/feld/{field}", data={"csrf_token": c.csrf, **data}, follow_redirects=False)


def test_stale_by_type_flag_and_owner(admin_client, user_client):
    """Prüffrist je Art (Lieferzeit 90 Tage, Hinweis 365), „stimmt nicht mehr“ melden, Zuständige sehen es zuerst."""
    a, u = admin_client, user_client
    nid = _topic(a, "Nordic Lights")
    _entry(a, "Nordic Lights Lieferzeit 6 Wochen")
    _entry(a, "Nordic Lights Hinweis: Katalog kommt im Frühjahr")
    with session_scope() as db:
        for e in db.query(KbEntry):
            e.checked_at = e.checked_at - timedelta(days=100)
        liefer = db.query(KbEntry).filter_by(type="liefer").one()
        other = db.query(KbEntry).filter(KbEntry.type != "liefer").one()
        assert kb.is_stale(liefer) and not kb.is_stale(other)
        anna_id, oid = db.query(User).filter_by(username="anna").one().id, other.id
    # Anna meldet den anderen Eintrag; Admin ist zuständig und sieht ihn unter „Du bist zuständig“
    a.post(f"/wissen/{nid}/zustaendig", data={"csrf_token": a.csrf, "benutzer": "1"})
    r = u.post(f"/wissen/eintrag/{oid}/melden", data={"csrf_token": u.csrf, "bemerkung": "Katalog kommt erst im Herbst",
                                                     "zurueck": str(nid)}, follow_redirects=False)
    assert r.status_code == 303
    page = a.get("/wissen").text
    assert "Du bist zuständig" in page and "Gemeldet „stimmt nicht mehr“ von anna" in page and "Katalog kommt erst im Herbst" in page
    assert page.index("Gemeldet „") < page.index('">Prüffrist abgelaufen</span>')  # gemeldete zuerst
    topic_page = u.get(f"/wissen/{nid}").text
    assert "Zuständig: admin" in topic_page and "gemeldet: Katalog kommt erst im Herbst" in topic_page
    # Bearbeiten erledigt die Meldung
    a.post(f"/wissen/eintrag/{oid}", data={"csrf_token": a.csrf, "text": "Katalog kommt im Herbst", "art": "hinweis",
                                         "themen": [str(nid)], "zurueck": str(nid)})
    with session_scope() as db:
        e = db.get(KbEntry, oid)
        assert e.flagged_at is None and e.flag_note is None
    assert "Ohne Zuständigen" not in a.get("/wissen").text
    u.post(f"/wissen/{nid}/zustaendig", data={"csrf_token": u.csrf, "benutzer": str(anna_id)})
    assert "Zuständig: anna" in a.get(f"/wissen/{nid}").text


def test_fields_flow_graph_and_hints_at_work(admin_client, user_client):
    """Feste Felder: Mindestmenge, Bezug darunter, Lagerartikel, Pflicht-Zubehör mit Menge. Daraus der Ablauf bei
    kleinen Mengen, Verknüpfungen und die Hinweisbox in Preisliste (Hersteller, Jahresabgleich) und Datenblatt."""
    a, u = admin_client, user_client
    nid, rid = _topic(a, "Nordic Lights", aliase="Nordic"), _topic(a, "Riedfeld")
    gid = _topic(a, "Montageadapter", art="gruppe")
    page = a.get(f"/wissen/{nid}").text
    assert "Bezugsregel festlegen" in page and 'name="lagerware"' in page  # leer: Satz zum Ausfüllen
    r = u.post(f"/wissen/{nid}/bezugsregel", data={"csrf_token": u.csrf, "moq": "36", "via": ""}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]  # ohne Händler
    r = u.post(f"/wissen/{nid}/bezugsregel", data={"csrf_token": u.csrf, "moq": "", "via": str(rid)}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]  # weder Menge noch Lagerware
    r = u.post(f"/wissen/{nid}/bezugsregel", data={"csrf_token": u.csrf, "moq": "36", "lagerware": "1", "via": str(rid),
                                                 "notiz": "dort andere Kalkulation"}, follow_redirects=False)
    assert r.headers["location"].endswith("#regel")
    _field(u, nid, "pflicht", wert=str(gid), menge="2", bemerkung="bei Dachmontage")
    page = a.get(f"/wissen/{nid}").text
    assert "Anfrage <b>Nordic Lights</b>: Ab 36 Stück oder Lagerware?" in page
    assert "Bei Nordic Lights bestellen" in page and "Bei Riedfeld bestellen →" in page
    assert "nein · unter 36 Stück und keine Lagerware" in page and "dort andere Kalkulation" in page
    assert '2 × <a href="/wissen/%d">Montageadapter</a>' % gid in page and "bei Dachmontage" in page
    assert 'class="kb-graph"' in page and "Pflicht-Zubehör · 1" in page
    assert "Für Nordic Lights: unter 36 Stück und keine Lagerware → hier bestellen" in a.get(f"/wissen/{rid}").text
    # Verlauf mit Namen
    assert "anna</b>" in page and "Angabe angelegt: Mindestbestellmenge: 36 Stück" in page
    # Hinweise in der Preisliste: Hersteller der eigenen Liste mit gleichem Namen/Alias
    from tests.test_datasheets import _content, _new, _save
    from backend.services import datasheets as ds

    with session_scope() as db:
        anna = db.query(User).filter_by(username="anna").one()
        m = Manufacturer(owner_id=anna.id, name="Nordic", code="NL")
        db.add(m)
        db.flush()
        mid = m.id
    box = u.get(f"/hersteller/{mid}").text
    assert 'class="kb-hintbox"' in box
    assert "Ab 36 Stück oder Lagerware → bei Nordic Lights bestellen, sonst (unter 36 Stück und keine Lagerware) → bei Riedfeld" in box
    assert "Pflicht-Zubehör: 2 × Montageadapter (bei Dachmontage)" in box
    # Datenblatt nennt Nordic Lights in einer Artikelbeschreibung: Hinweis im Editor
    sid = _new(u, titel="Arbeitsscheinwerfer", untertitel="Serie X")
    table = {**ds.new_table(), "zeilen": [{"bild": None, "artnr": "NL1", "farbe": "", "beschreibung": "Nordic Lights Scheinwerfer", "werte": []}]}
    _save(u, sid, _content(kopf={"titel": "Arbeitsscheinwerfer", "untertitel": "Serie X"}, bloecke=[*ds.DEFAULT_BLOCKS, table]))
    assert "Ab 36 Stück oder Lagerware" in u.get(f"/datenblatt/{sid}").text
    # nicht gefolgt: keine Hinweise
    u.post(f"/wissen/{nid}/folgen", data={"csrf_token": u.csrf})
    assert 'class="kb-hintbox"' not in u.get(f"/hersteller/{mid}").text
    # Regel entfernen: Händler weg, Mindestmenge bleibt als Angabe
    a.post(f"/wissen/{nid}/bezugsregel", data={"csrf_token": a.csrf, "aktion": "entfernen"})
    page = a.get(f"/wissen/{nid}").text
    assert "Bei Riedfeld bestellen" not in page and "Mindestbestellmenge 36 Stück ist eingetragen" in page


def test_search_words_synonyms_and_misses(admin_client, user_client):
    a, u = admin_client, user_client
    nid = _topic(a, "Nordic Lights", aliase="Nordic")
    _field(a, nid, "moq", wert="36")
    _entry(a, "Nordic Lights unter 36 Stück über Riedfeld anfragen")
    hits = u.get("/api/wissen/suche?q=moq nordic").json()["treffer"]  # Synonym (Startwert) + Wortreihenfolge egal
    assert any("Mindestbestellmenge: 36 Stück" in h["title"] for h in hits)
    assert u.get("/api/wissen/suche?q=riedfeld nordic").json()["treffer"]  # Wörter einzeln, nicht als Satz
    assert not u.get("/api/wissen/suche?q=riedfeld hella").json()["treffer"]  # jedes Wort muss passen
    page = u.get("/wissen/suche?q=moq").text
    assert "Auch gesucht nach: Mindestbestellmenge, Mindestmenge, Mindestabnahme" in page
    # ohne Treffer: nur die ausführliche Suche protokolliert, beim Tippen nicht
    u.get("/api/wissen/suche?q=drehlich")
    u.get("/wissen/suche?q=Drehlicht")
    u.get("/wissen/suche?q=drehlicht")
    terms = a.get("/wissen/suchbegriffe").text
    assert "<b>drehlicht</b>" in terms and '<td class="num">2</td>' in terms and "drehlich<" not in terms
    assert "Als Eintrag erfassen" in u.get("/wissen/suche?q=drehlicht").text
    # Synonym anlegen: Suche findet, Fehlliste wird bereinigt, Name und Zeit stehen dabei
    gid = _topic(a, "Rundumleuchten", art="gruppe")
    r = u.post("/wissen/suchbegriffe", data={"csrf_token": u.csrf, "woerter": "Rundumleuchten, Drehlicht"}, follow_redirects=False)
    assert r.status_code == 303
    assert any(h["url"] == f"/wissen/{gid}" for h in u.get("/api/wissen/suche?q=drehlicht").json()["treffer"])
    terms = a.get("/wissen/suchbegriffe").text
    assert "<b>drehlicht</b>" not in terms and "Rundumleuchten, Drehlicht" in terms and "anna," in terms
    r = u.post("/wissen/suchbegriffe", data={"csrf_token": u.csrf, "woerter": "nurEins"}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]
    assert "Nordic Lights unter 36" in a.get("/wissen?neu=test").text and ">test</textarea>" in a.get("/wissen?neu=test").text


def _product(c, gid, maker, artnr, scores, note=""):
    data = {"csrf_token": c.csrf, "hersteller": str(maker), "artnr": artnr, "name": "", "notiz": note}
    data.update({f"k{i}": str(v) for i, v in enumerate(scores) if v})
    return c.post(f"/wissen/{gid}/artikel", data=data, follow_redirects=False)


def test_product_comparison_ranking_and_hints(admin_client, user_client):
    """Artikelgruppe mit Artikeln mehrerer Hersteller: Punkte je Kriterium, Rang und Stufe nach Schnitt; der Hersteller
    sieht seinen Platz; Hinweis „erste Wahl“; Kriterien umbenennen behält die Punkte; Suche findet Artikel."""
    a, u = admin_client, user_client
    gid = _topic(a, "Blue-Spot-Scheinwerfer", art="gruppe")
    durite, other = _topic(a, "Durite"), _topic(a, "Nordic Lights")
    assert _product(u, gid, durite, "0-420-01", [5, 5, 4, 4], "heller, robuster").status_code == 303   # 4,5 → erste Wahl
    _product(u, gid, other, "NL-77", [3, 4, 3, None])                                                 # 3,33 → nur wenn nötig
    _product(u, gid, other, "NL-99", [None, None, None, None])                                         # unbewertet
    assert "fehler=" in _product(u, gid, gid, "X", [5]).headers["location"]  # Gruppe ist kein Hersteller
    r = u.post(f"/wissen/{durite}/artikel", data={"csrf_token": u.csrf, "hersteller": str(durite), "artnr": "X"},
               follow_redirects=False)
    assert "fehler=" in r.headers["location"]  # Vergleich nur in Artikelgruppen
    page = a.get(f"/wissen/{gid}").text
    assert page.index("0-420-01") < page.index("NL-77") < page.index("NL-99")
    assert ">4,5</b>" in page and "erste Wahl" in page and "nur wenn nötig" in page and "noch nicht bewertet" in page
    assert "heller, robuster" in page and "anna," in page
    maker = a.get(f"/wissen/{durite}").text
    assert "In Artikelgruppen" in maker and "Platz 1 von 2 · erste Wahl" in maker and 'class="kb-graph"' in maker
    # Hinweise: Gruppe nennt die erste Wahl, Hersteller wo er erste Wahl ist
    with session_scope() as db:
        user = db.query(User).filter_by(username="anna").one()
        g, d = db.get(KbTopic, gid), db.get(KbTopic, durite)
        texts = [h["text"] for h in kb.hints(db, user, [g, d])]
    assert "Blue-Spot-Scheinwerfer: erste Wahl Durite 0-420-01 (4,5)" in texts
    assert "Erste Wahl bei Blue-Spot-Scheinwerfer: Durite 0-420-01" in texts
    # Kriterien umbenennen: Punkte bleiben (nach Position)
    u.post(f"/wissen/{gid}/kriterien", data={"csrf_token": u.csrf, "kriterien": "Leuchtkraft, Qualität, Preis, Lieferbarkeit"})
    with session_scope() as db:
        from backend.models.entities import KbProduct
        p = db.query(KbProduct).filter_by(artnr="0-420-01").one()
        assert p.scores["Leuchtkraft"] == 5 and "Helligkeit" not in p.scores
        pid = p.id
    assert "Leuchtkraft" in a.get(f"/wissen/{gid}").text
    assert any("0-420-01" in h["title"] for h in u.get("/api/wissen/suche?q=0-420-01").json()["treffer"])
    assert any("0-420-01" in h["title"] for h in u.get("/api/wissen/suche?q=durite blue").json()["treffer"])
    a.post(f"/wissen/artikel/{pid}/loeschen", data={"csrf_token": a.csrf})
    page = a.get(f"/wissen/{gid}").text
    i = page.find("0-420-01")
    assert i < 0, page[i - 400:i + 60]
    assert "artikel gelöscht" in page


def test_map_data(admin_client, user_client):
    a, u = admin_client, user_client
    gid = _topic(a, "Blue-Spot-Scheinwerfer", art="gruppe")
    durite, nordic, ried = _topic(a, "Durite"), _topic(a, "Nordic Lights"), _topic(a, "Riedfeld")
    _product(a, gid, durite, "0-420-01", [5, 5, 4, 4])
    _field(a, nordic, "bezug_klein", wert=str(ried))
    _entry(a, "Nordic Lights und Durite liefern beide Blue-Spot-Scheinwerfer")
    u.post(f"/wissen/{nordic}/folgen", data={"csrf_token": u.csrf})
    d = u.get("/api/wissen/karte").json()
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes[nordic]["off"] and not nodes[durite]["off"] and nodes[gid]["kind"] == "gruppe"
    kinds = {(e["a"], e["b"], e["type"]): e for e in d["edges"]}
    art = kinds[(min(durite, gid), max(durite, gid), "artikel")]
    assert art["stage"] == "erste"
    assert (min(nordic, ried), max(nordic, ried), "bezug") in kinds
    assert (min(nordic, durite), max(nordic, durite), "eintrag") in kinds
    page = u.get("/wissen").text
    assert "data-kb-map" in page and "/static/knowledge_map.js" in page
    assert "data-kb-map" not in u.get(f"/wissen/{gid}").text  # Karte nur auf der Startseite


def test_map_infos_and_field_suggestions(admin_client, user_client):
    """Karte: beim Anklicken gehen Kärtchen mit Angaben, Einträgen und erster Wahl auf. Eintippen erkennt
    Mindestbestellmenge/Lieferzeit und übernimmt sie nur mit Häkchen als Angabe."""
    a, u = admin_client, user_client
    nid, gid = _topic(a, "Nordic Lights", aliase="Nordic"), _topic(a, "Blue-Spot-Scheinwerfer", art="gruppe")
    _product(a, gid, nid, "NL-1", [5, 5, 5, 4])
    r = u.post("/wissen/vorschlag", json={"text": "nordic Mindestbestellmenge auf den meisten Artikel = 36 Stück"},
               headers={"X-CSRF-Token": u.csrf})
    assert r.json()["angaben"] == [{"field": "moq", "value": "36", "label": "Mindestbestellmenge 36 Stück"}]
    # ohne Häkchen: nur Eintrag
    _entry(u, "nordic Mindestbestellmenge auf den meisten Artikel = 36 Stück")
    with session_scope() as db:
        assert not kb.field_facts(db, nid).get("moq")
    # mit Häkchen: zusätzlich Angabe; falsches Thema oder anderer Wert wird ignoriert
    _entry(u, "nordic lieferzeit 6 wochen", **{"angabe_lieferzeit": f"{gid}|6 Wochen"})
    _entry(u, "nordic moq 24 stk", **{"angabe_moq": f"{nid}|24"})
    with session_scope() as db:
        f = kb.field_facts(db, nid)
        assert f["moq"][0].number == 24 and not f.get("lieferzeit")
    d = u.get("/api/wissen/karte").json()
    info = {n["id"]: n["info"] for n in d["nodes"]}
    texts = [i["text"] for i in info[nid]]
    assert "Mindestbestellmenge: 24 Stück" in texts
    assert any("Mindestbestellmenge auf den meisten Artikel" in t for t in texts)
    assert any(t.startswith("Erste Wahl bei Blue-Spot-Scheinwerfer") for t in texts)
    assert any(i["text"].startswith("Blue-Spot-Scheinwerfer: erste Wahl Nordic Lights NL-1") for i in info[gid])
    assert len(info[nid]) <= kb.MAP_INFO_MAX



def test_map_condition_arrow_and_reverse(admin_client, user_client):
    """Nordic Lights: Mindestbestellmenge 36, darunter über Riedfeld. Karte: Pfeil Nordic → Riedfeld „unter 36 Stk“,
    Kärtchen bei Nordic mit Sprungziel Riedfeld, bei Riedfeld die Gegenrichtung. So legt es auch „Verbinden“ an."""
    a, u = admin_client, user_client
    nid, rid = _topic(a, "Nordic Lights"), _topic(a, "Riedfeld")
    gid, acc = _topic(a, "Arbeitsscheinwerfer", art="gruppe"), _topic(a, "Montageadapter", art="gruppe")
    # wie das Fenster auf der Karte: Bezugsregel, Pflicht-Zubehör, Hinweis zu beiden
    r = u.post(f"/wissen/{nid}/bezugsregel", data={"moq": "36", "lagerware": "1", "via": str(rid)},
               headers={"X-CSRF-Token": u.csrf})
    assert r.status_code == 200 and "fehler=" not in str(r.url)
    u.post(f"/wissen/{gid}/feld/pflicht", data={"wert": str(acc), "menge": "2"}, headers={"X-CSRF-Token": u.csrf})
    u.post("/wissen/eintrag", data={"text": "gleiche Halter", "themen": [str(nid), str(gid)]}, headers={"X-CSRF-Token": u.csrf})
    d = u.get("/api/wissen/karte").json()
    edges = {e["type"]: e for e in d["edges"]}
    assert edges["bezug"]["source"] == nid and edges["bezug"]["label"] == "unter 36 Stk / keine Lagerware"
    assert edges["pflicht"]["source"] == gid and edges["pflicht"]["label"] == "2 ×"
    assert "eintrag" in edges
    info = {n["id"]: n["info"] for n in d["nodes"]}
    card = next(i for i in info[nid] if i.get("target") == rid)
    assert card["type"] == "regel" and info[nid][0] is card  # Regel-Kärtchen zuerst
    assert card["text"] == "Bezugsregel: ab 36 Stück oder Lagerware → Nordic Lights, sonst → Riedfeld"
    assert not any(i["text"].startswith("Mindestbestellmenge:") for i in info[nid])  # zusammengefasst
    back = next(i for i in info[rid] if i.get("target") == nid)
    assert back["text"] == "Für Nordic Lights: unter 36 Stück und keine Lagerware → hier bestellen"
    node = {n["id"]: n for n in d["nodes"]}[nid]
    assert node["rule"] == {"moq": 36, "stock": True, "note": "", "via": rid}
    assert any(i["text"] == "Pflicht-Zubehör für Arbeitsscheinwerfer (2 ×)" for i in info[acc])
    assert {n["id"]: n["moq"] for n in d["nodes"]}[nid] == 36
    # Mindmap-Blasen: Hersteller zeigt die Bezugsregel als Blase
    bubbles = u.get(f"/api/wissen/blasen?f={nid}").json()["bubbles"]
    assert any(b["type"] == "bezug" and "Riedfeld" in b["label"] for b in bubbles)


def test_company_groups_parent_child_map_and_search(admin_client, user_client):
    """EccoESG ist Mutter von LED Autolamps und Vision Alert: Steckbrief zeigt die Gruppe, Karte liefert die Gruppe
    für die Blase, Suche nach der Mutter findet die Töchter, Kreise werden verhindert, Lösen geht."""
    a, u = admin_client, user_client
    ecco, led, vis = _topic(a, "EccoESG"), _topic(a, "LED Autolamps"), _topic(a, "Vision Alert")
    grp = _topic(a, "Leuchtbalken", art="gruppe")
    r = u.post(f"/wissen/{led}/firmengruppe", data={"csrf_token": u.csrf, "mutter": str(ecco)}, follow_redirects=False)
    assert r.headers["location"].endswith("#firmengruppe")
    u.post(f"/wissen/{ecco}/firmengruppe", data={"csrf_token": u.csrf, "tochter": str(vis)})   # von der Mutter aus
    r = u.post(f"/wissen/{ecco}/firmengruppe", data={"csrf_token": u.csrf, "mutter": str(led)}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]  # Kreis
    r = u.post(f"/wissen/{led}/firmengruppe", data={"csrf_token": u.csrf, "mutter": str(grp)}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]  # nur Hersteller
    page = a.get(f"/wissen/{vis}").text
    assert "kb-company-chip root" in page and "EccoESG <small>Mutter</small>" in page and "LED Autolamps" in page
    assert ">Vision Alert</a>" in page.split("kb-company-members")[1].split("</div>")[0]
    assert "Firmengruppe · " in page  # Verknüpfungsbild zeigt die Gruppe
    d = u.get("/api/wissen/karte").json()
    assert d["groups"] == [{"id": ecco, "name": "EccoESG", "members": [ecco, led, vis]}]
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes[led]["group"] == ecco and nodes[led]["parent"] == ecco and nodes[grp]["group"] is None
    assert any(i["text"] == "Gehört zur Firmengruppe EccoESG" and i["target"] == ecco for i in nodes[vis]["info"])
    assert any("Töchter LED Autolamps, Vision Alert" in i["text"] for i in nodes[ecco]["info"])
    titles = [h["title"] for h in u.get("/api/wissen/suche?q=ecco").json()["treffer"]]
    assert {"EccoESG", "LED Autolamps", "Vision Alert"} <= set(titles)
    with session_scope() as db:
        assert [c.action for c in kb.history(db, "thema", led)][:1] == ["Firmengruppe"]
    # Tochter lösen
    u.post(f"/wissen/{ecco}/firmengruppe", data={"csrf_token": u.csrf, "tochter": str(vis), "loesen": "1"})
    assert u.get("/api/wissen/karte").json()["groups"][0]["members"] == [ecco, led]


def test_start_page_list_map_and_info_panel(user_client):
    """Startseite: Liste links (Firmengruppen eingerückt), Karte, Infofenster rechts; Infofenster per ?t= und als
    Baustein nachladbar; Eintragen/Prüfen aus dem Fenster springt zurück auf die Startseite mit offenem Fenster."""
    u = user_client
    ecco, led = _topic(u, "EccoESG"), _topic(u, "LED Autolamps")
    nordic, ried = _topic(u, "Nordic Lights"), _topic(u, "Riedfeld")
    u.post(f"/wissen/{led}/firmengruppe", data={"csrf_token": u.csrf, "mutter": ecco})
    u.post(f"/wissen/{nordic}/bezugsregel", data={"csrf_token": u.csrf, "moq": "36", "lagerware": "1", "via": ried})
    u.post(f"/wissen/{nordic}/feld/lieferzeit", data={"csrf_token": u.csrf, "wert": "4-6 Wochen"})

    page = u.get("/wissen").text
    assert 'class="kb-work"' in page and "Überblick" in page and "data-kb-map" in page and "data-map-say" in page
    assert re.search(r'<li class="child grp c\d"[^>]*>\s*<a href="/wissen\?f=%d" data-pick="%d" data-kind="hersteller"><span>LED Autolamps' % (led, led), page)

    # Infofenster per Link (ohne Script) und als Baustein
    page = u.get(f"/wissen?t={nordic}").text
    assert 'data-sel-f="%d"' % nordic in page  # Link öffnet die Auswahl (Blasen lädt das Script)
    frag = u.get(f"/wissen/{nordic}/kurz").text
    assert "<html" not in frag and "Unter 36 Stück und keine Lagerware" in frag and "Riedfeld" in frag
    assert "Fehlt: Ansprechpartner, Pflicht-Zubehör" in frag
    assert "Firmengruppe" in u.get(f"/wissen/{led}/kurz").text
    ried_frag = u.get(f"/wissen/{ried}/kurz").text
    assert "Nordic Lights</a>: Für Nordic Lights" in ried_frag  # Gegenrichtung der Bezugsregel
    assert "Überblick" in u.get("/wissen/ueberblick").text

    # Schnell ergänzen aus dem Fenster: landet beim Thema, zurück auf die Startseite mit offenem Fenster
    r = u.post("/wissen/eintrag", data={"csrf_token": u.csrf, "text": "Garantie 5 Jahre", "vorgabe": nordic,
                                         "themen": nordic, "ziel": "start"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/wissen?t={nordic}#e")
    eid = int(r.headers["location"].split("#e")[1])
    assert "Garantie 5 Jahre." in u.get(f"/wissen/{nordic}/kurz").text
    r = u.post(f"/wissen/eintrag/{eid}/melden", data={"csrf_token": u.csrf, "zurueck": f"start:{nordic}",
                                                      "bemerkung": "jetzt 3 Jahre"}, follow_redirects=False)
    assert r.headers["location"] == f"/wissen?t={nordic}#e{eid}"
    assert "von anna: jetzt 3 Jahre" in u.get(f"/wissen/{nordic}/kurz").text
    r = u.post(f"/wissen/{nordic}/folgen", data={"csrf_token": u.csrf, "zurueck": f"/wissen?t={nordic}"},
               follow_redirects=False)
    assert r.headers["location"] == f"/wissen?t={nordic}"
    # leerer Text: Fehler zurück ins Fenster
    r = u.post("/wissen/eintrag", data={"csrf_token": u.csrf, "text": " ", "vorgabe": nordic, "themen": nordic,
                                         "ziel": "start"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/wissen?t={nordic}&fehler=")


def test_maker_times_group_panel(user_client):
    """Firmen links, Artikelgruppen rechts: Hersteller wählen nennt die Gruppen, zu denen es etwas gibt;
    Hersteller × Gruppe zeigt nur das Gemeinsame (Artikel, Einträge zu beiden, Pflicht-Zubehör, Allgemeines der Gruppe)."""
    u = user_client
    red, other = _topic(u, "Redtronic"), _topic(u, "Hella")
    balken, rund, adapter = _topic(u, "Leuchtbalken", "gruppe"), _topic(u, "Rundumleuchten", "gruppe"), _topic(u, "Montageadapter", "gruppe")
    u.post(f"/wissen/{balken}/artikel", data={"csrf_token": u.csrf, "hersteller": red, "artnr": "RT-120", "name": "Balken 120",
                                              "k0": "5", "k1": "5", "k2": "4"})
    u.post(f"/wissen/{balken}/artikel", data={"csrf_token": u.csrf, "hersteller": other, "artnr": "H-1", "name": "Hella Balken",
                                              "k0": "3", "k1": "3", "k2": "3"})
    u.post(f"/wissen/{red}/feld/pflicht", data={"csrf_token": u.csrf, "wert": adapter, "menge": "2"})
    _entry(u, "Redtronic Leuchtbalken über 1,80 m mehr kalkulieren", themen=[red, balken])
    _entry(u, "Leuchtbalken immer mit Kabelsatz anbieten", themen=[balken])
    _entry(u, "Redtronic Lieferzeit 3 Wochen", themen=[red])

    frag = u.get(f"/wissen/{red}/kurz").text
    rel = re.search(r'data-rel-f="([\d,]*)"', frag).group(1).split(",")
    assert sorted(map(int, rel)) == sorted([balken, adapter])  # Rundumleuchten: nichts → nicht hervorgehoben
    assert str(red) in re.search(r'data-rel-g="([\d,]*)"', u.get(f"/wissen/{balken}/kurz").text).group(1).split(",")

    frag = u.get(f"/wissen/kombi?f={red}&g={balken}").text
    assert "Redtronic <span class=\"kb-d-x\">×</span> Leuchtbalken" in frag
    assert "RT-120 · Balken 120" in frag and "Platz 1 von 2" in frag and "erste Wahl" in frag
    assert "Andere Hersteller in Leuchtbalken (1)" in frag
    assert "über 1,80 m mehr kalkulieren" in frag and "Gilt für alle Leuchtbalken" in frag and "Kabelsatz" in frag
    assert frag.index("Gilt für alles von Redtronic") < frag.index("Lieferzeit 3 Wochen")  # allgemein Redtronic: eigener Abschnitt
    assert "Pflicht-Zubehör" not in frag  # Montageadapter betrifft nicht Leuchtbalken
    page = u.get(f"/wissen?f={red}&g={balken}").text
    assert 'data-sel-f="%d" data-sel-g="%d"' % (red, balken) in page
    assert u.get(f"/wissen/kombi?f={balken}&g={red}").status_code == 404  # Art vertauscht

    # Eintrag aus der Kombi-Ansicht: gehört zu beiden, zurück in die Kombi-Ansicht
    r = u.post("/wissen/eintrag", data={"csrf_token": u.csrf, "text": "nur in 24 V", "vorgabe": red,
                                         "themen": [red, balken], "ziel": f"kombi:{red}:{balken}"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/wissen?f={red}&g={balken}#e")
    with session_scope() as db:
        assert sorted(db.query(KbEntry).filter(KbEntry.text.like("%24 V%")).one().topic_ids) == sorted([red, balken])


def test_assortment_assign_groups_to_maker(user_client):
    """Artikelgruppen beim Hersteller fest zuordnen (und von der Gruppe aus): bestimmt Hervorhebung und Kombination;
    Kombi-Ansicht zeigt auch, was für alles vom Hersteller gilt."""
    u = user_client
    red, balken, rund = _topic(u, "Redtronic"), _topic(u, "Leuchtbalken", "gruppe"), _topic(u, "Rundumleuchten", "gruppe")
    frag = u.get(f"/wissen/{red}/kurz").text
    assert "Welche Artikelgruppen führt Redtronic?" in frag and "Artikelgruppe hinzufügen …" in frag

    r = u.post("/wissen/sortiment", data={"csrf_token": u.csrf, "hersteller": red, "gruppe": balken,
                                          "zurueck": f"start:{red}"}, follow_redirects=False)
    assert r.headers["location"] == f"/wissen?t={red}"
    u.post("/wissen/sortiment", data={"csrf_token": u.csrf, "hersteller": red, "gruppe": balken})  # doppelt: egal
    frag = u.get(f"/wissen/{red}/kurz").text
    assert re.search(r'data-asg-f="%d"' % balken, frag) and str(balken) in re.search(r'data-rel-f="([\d,]*)"', frag).group(1)
    assert 'data-combine="%d"' % balken in frag
    assert re.search(r'data-asg-g="%d"' % red, u.get(f"/wissen/{balken}/kurz").text)  # Gegenseite

    # Kombi: zugeordnet, plus „Gilt für alles von Redtronic“
    u.post(f"/wissen/{red}/feld/lieferzeit", data={"csrf_token": u.csrf, "wert": "3 Wochen"})
    _entry(u, "Redtronic Preise netto ab Werk", themen=[red])
    frag = u.get(f"/wissen/kombi?f={red}&g={balken}").text
    assert 'class="kb-link on"' in frag and 'aria-label="Redtronic führt Leuchtbalken"' in frag and "Zuordnung lösen" in frag
    assert "Gilt für alles von Redtronic" in frag and "3 Wochen" in frag and "netto ab Werk" in frag
    frag = u.get(f"/wissen/kombi?f={red}&g={rund}").text
    assert "Rundumleuchten zu Redtronic hinzufügen" in frag and 'class="kb-link off"' in frag and "nicht zugeordnet" in frag

    # Karte: Linie Hersteller–Gruppe auch ohne Artikel im Vergleich
    edges = u.get("/api/wissen/karte").json()["edges"]
    assert any(e["type"] == "artikel" and {e["a"], e["b"]} == {red, balken} for e in edges)

    # Lösen, Verlauf, falsche Art
    u.post("/wissen/sortiment", data={"csrf_token": u.csrf, "hersteller": red, "gruppe": balken, "aktion": "entfernen"})
    assert 'data-asg-f=""' in u.get(f"/wissen/{red}/kurz").text
    r = u.post("/wissen/sortiment", data={"csrf_token": u.csrf, "hersteller": balken, "gruppe": red,
                                          "zurueck": f"start:{red}"}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]
    with session_scope() as db:
        actions = [c.action for c in db.query(kb.KbChange).filter_by(topic_id=red)]
    assert actions.count("Artikelgruppe") == 2


def test_series_in_group_with_maker(user_client):
    """Serien (z. B. Spartan = Leuchtbalken von Redtronic): anlegen bei Gruppe/Hersteller/Kombi, eigene Infos,
    Erkennung im Text, Ausgabe in Gruppe, Hersteller, Kombi und eigenem Fenster; nicht auf der Karte."""
    u = user_client
    red, balken = _topic(u, "Redtronic"), _topic(u, "Leuchtbalken", "gruppe")
    r = u.post("/wissen/serie", data={"csrf_token": u.csrf, "name": "Spartan", "gruppe": balken, "hersteller": red,
                                      "aliase": "Spartan LED", "zurueck": f"start:{balken}"}, follow_redirects=False)
    assert r.headers["location"] == f"/wissen?t={balken}"
    with session_scope() as db:
        sp = db.query(KbTopic).filter_by(kind="serie").one()
        assert (sp.name, sp.parent_id, sp.maker_id, sp.aliases) == ("Spartan", balken, red, ["Spartan LED"])
        spid = sp.id
    # Gruppe wird dem Hersteller automatisch zugeordnet
    assert re.search(r'data-asg-f="[\d,]*%d' % balken, u.get(f"/wissen/{red}/kurz").text)
    # nur über /wissen/serie, nicht als normales Thema; doppelt = dieselbe
    assert u.post("/wissen/thema", data={"csrf_token": u.csrf, "art": "serie", "name": "X"}, follow_redirects=False
                  ).headers["location"].startswith("/wissen?fehler=")
    u.post("/wissen/serie", data={"csrf_token": u.csrf, "name": "spartan", "gruppe": balken, "hersteller": red})

    # Infos zur Serie: Text mit „Spartan“ wird erkannt; Angabe Lieferzeit
    _entry(u, "Spartan gibt es nur bis 1,50 m")
    u.post(f"/wissen/{spid}/feld/lieferzeit", data={"csrf_token": u.csrf, "wert": "8 Wochen"})
    _entry(u, "Leuchtbalken immer mit Kabelsatz anbieten", themen=[balken])
    frag = u.get(f"/wissen/{spid}/kurz").text
    assert "Spartan gibt es nur bis 1,50 m." in frag and "8 Wochen" in frag
    assert "Artikelgruppe</small> Leuchtbalken" in frag and "Hersteller</small> Redtronic" in frag
    assert "Gilt für alle Leuchtbalken" in frag and "Kabelsatz" in frag

    # Ausgabe bei Gruppe, Hersteller, Kombi und in der Liste rechts
    for url in (f"/wissen/{balken}/kurz", f"/wissen/{red}/kurz", f"/wissen/kombi?f={red}&g={balken}"):
        assert 'data-only="%d"><b>Spartan</b>' % spid in u.get(url).text, url
    assert "Serien von Redtronic in Leuchtbalken" in u.get(f"/wissen/kombi?f={red}&g={balken}").text
    page = u.get("/wissen").text
    assert re.search(r'<li class="child serie"[^>]*>\s*<a href="/wissen\?t=%d" data-pick="%d" data-kind="serie"' % (spid, spid), page)
    assert "Spartan" in u.get(f"/wissen?f={red}&g={spid}").text  # Serie als „Gruppe“ gewählt: eigenes Fenster
    assert all(n["id"] != spid for n in u.get("/api/wissen/karte").json()["nodes"])
    assert u.get(f"/wissen/{spid}").status_code == 200  # Steckbrief


def test_delete_topic_with_confirmation(user_client):
    """Hersteller/Artikelgruppe löschen: Sicherheitsabfrage mit Auswirkungen, Einträge verlieren die Zuordnung bzw.
    werden gelöscht, Serien und Angaben gehen mit; Hersteller aus einer Preisliste sind gesperrt."""
    u = user_client
    red, balken, hella = _topic(u, "Redtronic"), _topic(u, "Leuchtbalken", "gruppe"), _topic(u, "Hella")
    u.post("/wissen/serie", data={"csrf_token": u.csrf, "name": "Spartan", "gruppe": balken, "hersteller": red})
    _entry(u, "Leuchtbalken immer mit Kabelsatz", themen=[balken])
    _entry(u, "Redtronic und Hella Leuchtbalken gleiche Halter", themen=[red, balken, hella])
    u.post(f"/wissen/{red}/feld/pflicht", data={"csrf_token": u.csrf, "wert": balken, "menge": "1"})

    page = u.get("/wissen").text
    assert 'href="/wissen/%d/loeschen"' % balken in page and 'href="/wissen/%d/loeschen"' % red in page
    conf = u.get(f"/wissen/{balken}/loeschen").text
    assert "Artikelgruppe löschen" in conf and "Leuchtbalken" in conf and "Serien: Spartan" in conf
    assert "1 Eintrag, der nur hierzu gehört" in conf and "bei 1 weiteren Eintrag wird nur die Zuordnung entfernt" in conf
    # ohne Häkchen passiert nichts
    r = u.post(f"/wissen/{balken}/loeschen", data={"csrf_token": u.csrf}, follow_redirects=False)
    assert r.headers["location"] == f"/wissen/{balken}/loeschen"
    r = u.post(f"/wissen/{balken}/loeschen", data={"csrf_token": u.csrf, "bestaetigt": "ja"}, follow_redirects=False)
    assert r.headers["location"] == "/wissen"
    with session_scope() as db:
        assert db.get(KbTopic, balken) is None and db.query(KbTopic).filter_by(kind="serie").count() == 0
        texts = {e.text: sorted(e.topic_ids) for e in db.query(KbEntry)}
        assert not any("Kabelsatz" in t for t in texts)
        assert sorted([red, hella]) in texts.values()
        assert db.query(kb.KbFact).filter(kb.KbFact.ref_topic_id == balken).count() == 0
    assert u.get("/wissen").status_code == 200 and u.get(f"/wissen/{red}/kurz").status_code == 200

    # Hersteller aus einer Preisliste: gesperrt
    with session_scope() as db:
        anna = db.query(User).filter_by(username="anna").one()
        db.add(Manufacturer(owner_id=anna.id, name="Redtronic", code="RT"))
    assert "steht in einer Preisliste" in u.get(f"/wissen/{red}/loeschen").text
    u.post(f"/wissen/{red}/loeschen", data={"csrf_token": u.csrf, "bestaetigt": "ja"})
    with session_scope() as db:
        assert db.get(KbTopic, red) is not None


def test_map_card_maker_group_pair(user_client):
    """Infofeld auf der Karte: nur Hersteller = Standard-Infos ohne Artikelgruppen; nur Gruppe = alles zur Gruppe,
    egal welcher Hersteller, sortiert (Allgemein, dann je Hersteller); beide = Kombination."""
    u = user_client
    red, hella, balken = _topic(u, "Redtronic"), _topic(u, "Hella"), _topic(u, "Leuchtbalken", "gruppe")
    u.post("/wissen/serie", data={"csrf_token": u.csrf, "name": "Spartan", "gruppe": balken, "hersteller": red})
    u.post(f"/wissen/{red}/feld/lieferzeit", data={"csrf_token": u.csrf, "wert": "3 Wochen"})
    _entry(u, "Redtronic Rabatt ab 10 Stück", themen=[red])
    _entry(u, "Redtronic Leuchtbalken mit Montagesatz", themen=[red, balken])
    _entry(u, "Hella Leuchtbalken nur 12 V", themen=[hella, balken])
    _entry(u, "Leuchtbalken über 1,80 m mehr kalkulieren", themen=[balken])
    _entry(u, "Spartan nur bis 1,50 m")

    m = u.get(f"/wissen/karteninfo?f={red}").text
    assert "Redtronic" in m and "3 Wochen" in m and "Rabatt ab 10 Stück" in m
    assert "Montagesatz" not in m and "1,50 m" not in m  # nichts mit Artikelgruppe/Serie

    g = u.get(f"/wissen/karteninfo?g={balken}").text
    assert "alle Hersteller" in g and "1,80 m mehr kalkulieren" in g and "Montagesatz" in g and "nur 12 V" in g
    assert "1,50 m" in g and "Serie Spartan" in g  # Serien-Einträge beim Hersteller der Serie
    assert g.index("Für alle Leuchtbalken") < g.index("<span>Hella</span>") < g.index("<span>Redtronic</span>")  # sortiert
    assert "Rabatt ab 10 Stück" not in g

    k = u.get(f"/wissen/karteninfo?f={red}&g={balken}").text
    assert "Redtronic → Leuchtbalken" in k and "Montagesatz" in k and "1,80 m" in k and "3 Wochen" in k
    assert "Spartan" in k and "nur 12 V" not in k
    with session_scope() as db:
        sp = db.query(KbTopic).filter_by(kind="serie").one().id
    assert "1,50 m" in u.get(f"/wissen/karteninfo?g={sp}").text
    assert u.get("/wissen/karteninfo").status_code == 404



def test_bubbles_maker_group_pair(user_client):
    """Mindmap-Blasen: nur Hersteller = Standard-Infos ohne Artikelgruppen; nur Gruppe = alles zur Gruppe (alle
    Hersteller, mit Namen); Hersteller + Gruppe = nur die Infos dieser Gruppe beim Hersteller."""
    u = user_client
    red, hella, balken = _topic(u, "Redtronic"), _topic(u, "Hella"), _topic(u, "Leuchtbalken", "gruppe")
    u.post("/wissen/serie", data={"csrf_token": u.csrf, "name": "Spartan", "gruppe": balken, "hersteller": red})
    u.post(f"/wissen/{red}/feld/lieferzeit", data={"csrf_token": u.csrf, "wert": "3 Wochen"})
    _entry(u, "Redtronic Rabatt ab 10 Stück", themen=[red])
    _entry(u, "Redtronic Leuchtbalken mit Montagesatz", themen=[red, balken])
    _entry(u, "Hella Leuchtbalken nur 12 V", themen=[hella, balken])
    _entry(u, "Leuchtbalken über 1,80 m mehr kalkulieren", themen=[balken])
    _entry(u, "Spartan nur bis 1,50 m")

    def labels(q):
        return [b["label"] for b in u.get("/api/wissen/blasen?" + q).json()["bubbles"]]
    m = labels(f"f={red}")
    assert "Lieferzeit: 3 Wochen" in m and any("Rabatt" in x for x in m)
    assert not any("Montagesatz" in x or "1,50 m" in x for x in m)
    g = labels(f"g={balken}")
    assert any(x.startswith("Hella: ") and "12 V" in x for x in g) and any(x.startswith("Redtronic: ") and "Montagesatz" in x for x in g)
    assert any("1,80 m" in x and ":" not in x.split("1,80")[0] for x in g) and "Serie Spartan (Redtronic) (1) ›" in g
    assert not any("1,50 m" in x for x in g) and not any("Rabatt" in x for x in g)  # Serien-Infos hinter der Serie
    k = u.get(f"/api/wissen/blasen?f={red}&g={balken}").json()
    kl = [b["label"] for b in k["bubbles"]]
    assert any("Montagesatz" in x for x in kl) and "Serie Spartan (1) ›" in kl and not any("1,50 m" in x for x in kl)
    sp = next(b for b in k["bubbles"] if b["kind"] == "serie")
    sub = [b["label"] for b in u.get(f"/api/wissen/blasen?g={sp['series']}").json()["bubbles"]]
    assert any("1,50 m" in x for x in sub)  # aufgeklappte Serie
    # Serie heißt schon „Serie …“: kein doppeltes „Serie Serie“
    u.post("/wissen/serie", data={"csrf_token": u.csrf, "name": "Serie Nova", "gruppe": balken, "hersteller": red})
    assert any(x.startswith("Serie Nova (") for x in labels(f"f={red}&g={balken}"))
    assert not any("12 V" in x or "1,80 m" in x or "Rabatt" in x for x in kl)
    assert k["assigned"] is True and balken in u.get(f"/api/wissen/blasen?f={red}").json()["lit"]
    e = next(b for b in k["bubbles"] if b["kind"] == "eintrag")
    assert e["entry"] and e["who"] == "anna" and sorted(e["topics"]) == sorted([red, balken])
    assert u.get("/api/wissen/blasen").status_code == 404
    # Steckbrief: Artikelgruppen zuordnen und Serien anlegen
    page = u.get(f"/wissen/{red}").text
    assert 'id="sortiment"' in page and "Spartan" in page and "Serie anlegen" in page


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_pdf_attachment_on_entries(user_client, settings):
    """PDF an Einträgen: beim Eintragen oder später hochladen, in der Blase mit Dateinamen, öffnen, ersetzen,
    entfernen; nur echte PDFs; Datei verschwindet mit dem Eintrag."""
    u = user_client
    red = _topic(u, "Redtronic")
    r = u.post("/wissen/eintrag", data={"csrf_token": u.csrf, "text": "Spartan Datenblatt", "vorgabe": red, "themen": red,
                                         "ziel": "start"},
               files={"datei": ("Spartan Datenblatt.pdf", PDF, "application/pdf")}, follow_redirects=False)
    assert r.status_code == 303 and "fehler" not in r.headers["location"], r.headers["location"]
    eid = int(r.headers["location"].split("#e")[1])
    b = next(x for x in u.get(f"/api/wissen/blasen?f={red}").json()["bubbles"] if x.get("entry") == eid)
    assert b["file"] == {"name": "Spartan Datenblatt.pdf", "url": f"/wissen/datei/{eid}"}
    f = u.get(f"/wissen/datei/{eid}")
    assert f.status_code == 200 and f.content == PDF and f.headers["content-type"] == "application/pdf"
    assert f.headers["content-disposition"].startswith("inline;")
    files = list((settings.data_dir / "wissen").glob("*.pdf"))
    assert len(files) == 1
    assert "PDF · Spartan Datenblatt.pdf" in u.get(f"/wissen/{red}").text  # Steckbrief

    # Kein PDF: abgelehnt, nichts angelegt
    r = u.post("/wissen/eintrag", data={"csrf_token": u.csrf, "text": "Bild", "vorgabe": red, "themen": red, "ziel": "start"},
               files={"datei": ("bild.pdf", b"GIF89a....", "application/pdf")}, follow_redirects=False)
    assert "fehler=" in r.headers["location"]
    with session_scope() as db:
        assert db.query(KbEntry).filter(KbEntry.text.like("Bild%")).count() == 0
    # Nur PDF ohne Text: Dateiname als Text
    r = u.post("/wissen/eintrag", data={"csrf_token": u.csrf, "text": "", "vorgabe": red, "themen": red, "ziel": "start"},
               files={"datei": ("Preisliste 2027.pdf", PDF, "application/pdf")}, follow_redirects=False)
    with session_scope() as db:
        assert db.query(KbEntry).filter(KbEntry.file_name == "Preisliste 2027.pdf").one().text.startswith("Preisliste 2027")

    # Ersetzen, entfernen, löschen räumt auf
    u.post(f"/wissen/eintrag/{eid}/datei", data={"csrf_token": u.csrf}, files={"datei": ("neu.pdf", PDF, "application/pdf")})
    assert u.get(f"/wissen/datei/{eid}").headers["content-disposition"].endswith("neu.pdf")
    assert len(list((settings.data_dir / "wissen").glob("*.pdf"))) == 2  # alte Datei weg, plus „Preisliste 2027“
    u.post(f"/wissen/eintrag/{eid}/datei", data={"csrf_token": u.csrf, "entfernen": "1"})
    assert u.get(f"/wissen/datei/{eid}").status_code == 404
    u.post(f"/wissen/eintrag/{eid}/datei", data={"csrf_token": u.csrf}, files={"datei": ("x.pdf", PDF, "application/pdf")})
    u.post(f"/wissen/eintrag/{eid}/loeschen", data={"csrf_token": u.csrf, "bestaetigt": "ja"})
    assert len(list((settings.data_dir / "wissen").glob("*.pdf"))) == 1
    with session_scope() as db:
        actions = [c.action for c in db.query(kb.KbChange).filter_by(object="eintrag", object_id=eid)]
    assert "PDF angehängt" in actions and "PDF entfernt" in actions
