"""Modul „Vertriebswissen“: gemeinsames Wissen zu Herstellern und Artikelgruppen."""

from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.database.engine import get_db
from backend.models.entities import KbChange, KbEntry, KbFact, KbProduct, KbSearchMiss, KbTopic, User, utcnow
from backend.services import knowledge as kb
from backend.services.audit import audit

router = APIRouter()


def _topic(db: Session, topic_id: int) -> KbTopic:
    t = db.get(KbTopic, topic_id)
    if t is None:
        raise HTTPException(404, "Nicht gefunden")
    return t


def _entry(db: Session, entry_id: int, user: User) -> KbEntry:
    e = db.get(KbEntry, entry_id)
    if e is None or not kb.can_see(e, user):  # private Einträge anderer: wie nicht vorhanden
        raise HTTPException(404, "Eintrag nicht gefunden")
    return e


def _back(topic_id: int | None, error: str | None = None, anchor: str = "") -> RedirectResponse:
    url = f"/wissen/{topic_id}" if topic_id else "/wissen"
    if error:
        url += "?fehler=" + quote(error)
    return RedirectResponse(url + anchor, status_code=303)


def _context(db: Session, user: User, error: str | None) -> dict:
    kb.sync_manufacturers(db)
    all_topics = kb.topics(db)
    hidden = kb.unfollowed(db, user)
    names = {u.id: u.username for u in db.scalars(select(User))}
    visible = list(db.scalars(kb.visible_entries(db, user)))
    counts: dict[int, int] = {}
    for e in visible:
        for t in e.topic_ids or []:
            counts[t] = counts.get(t, 0) + 1
    pcounts: dict[int, int] = {}
    for g_id, m_id in db.execute(select(KbProduct.group_id, KbProduct.maker_id)):
        for t in (g_id, m_id):
            if t:
                pcounts[t] = pcounts.get(t, 0) + 1
    return {"portal": True, "topics": all_topics, "hidden": hidden, "names": names, "counts": counts, "pcounts": pcounts,
            "types": kb.TYPES, "kinds": kb.KINDS, "error": error, "is_stale": kb.is_stale, "due_date": kb.due_date,
            "topic_json": json.dumps([{"id": t.id, "name": t.name, "kind": kb.KINDS[t.kind]} for t in all_topics],
                                     ensure_ascii=False)}


def _incoming_text(db: Session, f: KbFact, by_id: dict) -> str:
    """Was ein anderes Thema über dieses festlegt, aus Sicht dieses Themas."""
    src = by_id[f.topic_id].name
    if f.field == "bezug_klein":
        moq = (kb.field_facts(db, f.topic_id).get("moq") or [None])[0]
        return f"Für {src}: Anfragen unter {moq.number} Stück kommen hierher" if moq and moq.number else f"Für {src}: kleine Mengen kommen hierher"
    if f.field == "pflicht":
        return f"Pflicht-Zubehör für {src} ({f.number or 1} × je Artikel)"
    return f"{src}: {f.label}"


@router.get("/wissen")
def overview(request: Request, fehler: str | None = None, neu: str | None = None, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    ctx = _context(db, user, fehler)
    hidden, by_id = ctx["hidden"], {t.id: t for t in ctx["topics"]}
    followed = [e for e in db.scalars(kb.visible_entries(db, user).order_by(KbEntry.updated_at.desc()))
                if any(t not in hidden for t in e.topic_ids or [])]
    return render(request, "knowledge.html", {**ctx, "topic": None, "recent": followed[:12],
                                              "attention": kb.attention(db, user), "by_id": by_id,
                                              "prefill": (neu or "")[:200]})


@router.get("/wissen/suche")
def search_page(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    ctx = _context(db, user, None)
    hits = kb.search(db, user, q, limit=60)
    if q.strip() and not hits:
        kb.record_miss(db, user, q)  # für die Liste „Suchen ohne Treffer“ (nur die ausführliche Suche, nicht beim Tippen)
    return render(request, "knowledge_search.html", {**ctx, "q": q, "hits": hits, "also": kb.synonyms_used(db, q)})


@router.get("/wissen/suchbegriffe")
def terms_page(request: Request, fehler: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    """Synonyme pflegen und sehen, wonach gesucht und nichts gefunden wurde."""
    ctx = _context(db, user, fehler)
    groups = kb.synonym_groups(db)
    return render(request, "knowledge_terms.html", {**ctx, "groups": groups, "misses": kb.misses(db)})


@router.post("/wissen/suchbegriffe", dependencies=[Depends(check_csrf)])
async def save_terms(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    gid = str(form.get("id") or "")
    try:
        kb.save_synonyms(db, user, int(gid) if gid.isdigit() else None, str(form.get("woerter") or ""))
    except ValueError as exc:
        return RedirectResponse("/wissen/suchbegriffe?fehler=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/wissen/suchbegriffe", status_code=303)


@router.post("/wissen/suchbegriffe/fehl/{miss_id}/erledigt", dependencies=[Depends(check_csrf)])
def miss_done(miss_id: int, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    row = db.get(KbSearchMiss, miss_id)
    if row:
        db.delete(row)
    return RedirectResponse("/wissen/suchbegriffe#fehl", status_code=303)


@router.get("/api/wissen/karte")
def map_api(db: Session = Depends(get_db), user: User = Depends(current_user)):
    kb.sync_manufacturers(db)
    return kb.map_data(db, user)


@router.get("/api/wissen/suche")
def search_api(q: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"treffer": [{k: h[k] for k in ("url", "title", "sub")} for h in kb.search(db, user, q, limit=12)]}


@router.post("/wissen/vorschlag", dependencies=[Depends(check_csrf)])
async def suggest(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    """Live-Vorschlag beim Tippen: Art, erkannte Themen und Schreibweise, so wie gespeichert würde."""
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Ungültige Daten")
    text = str((data or {}).get("text") or "")[:kb.MAX_TEXT]
    all_topics = kb.topics(db)
    found = kb.detect(text, all_topics)
    return {"art": found["type"], "themen": found["topic_ids"], "text": kb.tidy(text, all_topics),
            "angaben": kb.field_suggestions(text)}


@router.post("/wissen/thema", dependencies=[Depends(check_csrf)])
async def create_topic(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    kind, name = str(form.get("art") or ""), str(form.get("name") or "")
    if kind in kb.KINDS and kb.find_topic(db, kind, name):
        return _back(kb.find_topic(db, kind, name).id)
    try:
        t = kb.create_topic(db, user, kind, name, str(form.get("aliase") or ""))
    except ValueError as exc:
        return _back(None, str(exc))
    audit(db, user, "wissen_thema_angelegt", "kb_topic", t.id, {"name": t.name, "art": t.kind}, client_ip(request))
    return _back(t.id)


@router.get("/wissen/{topic_id}")
def topic_page(request: Request, topic_id: int, fehler: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    ctx = _context(db, user, fehler)
    t = _topic(db, topic_id)
    by_id = {x.id: x for x in ctx["topics"]}
    entries = kb.entries_for(db, user, t.id)
    grouped = [(k, label, [e for e in entries if e.type == k]) for k, label in kb.TYPES.items()]
    fields = kb.field_facts(db, t.id)
    facts = kb.free_facts(db, t.id)
    # Verbindungen auch über feste Felder anderer Themen, die hierher zeigen (z. B. „Darunter über Riedfeld“)
    incoming = list(db.scalars(select(KbFact).where(KbFact.ref_topic_id == t.id)))
    links = [f for fs in fields.values() for f in fs] + [
        KbFact(field=f.field, ref_topic_id=f.topic_id, topic_id=t.id) for f in incoming]
    if t.kind == "gruppe":
        compare, maker_rows = kb.group_products(db, t), []
        related = [r["p"].maker_id for r in compare if r["p"].maker_id]
    else:
        compare, maker_rows = [], kb.maker_products(db, t, by_id)
        related = [r["group"].id for r in maker_rows]
    near = [(by_id[i], kind, n) for i, kind, n in kb.neighbours(entries, t.id, links, related) if i in by_id]
    histories = {e.id: kb.history(db, "eintrag", e.id) for e in entries}
    changes = list(db.scalars(select(KbChange).where(KbChange.topic_id == t.id).order_by(KbChange.at.desc()).limit(15)))
    return render(request, "knowledge.html", {
        **ctx, "topic": t, "grouped": grouped, "entries": entries, "facts": facts, "by_id": by_id,
        "fields": fields, "field_defs": kb.FIELDS, "field_keys": kb.FIELDS_BY_KIND[t.kind], "lager_choices": kb.LAGER_CHOICES,
        "describe": kb.describe, "fact_stale": kb.fact_stale, "flow": kb.flow(t, fields, by_id), "due_date": kb.due_date,
        "users": [u for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.username))],
        "referenced_by": [(by_id[f.topic_id], _incoming_text(db, f, by_id)) for f in incoming if f.topic_id in by_id],
        "graph": kb.graph(t, near) if near else None, "histories": histories, "changes": changes,
        "own": kb.own_manufacturers(db, t, user), "following": t.id not in ctx["hidden"], "is_stale": kb.is_stale,
        "compare": compare, "maker_rows": maker_rows, "criteria": kb.criteria_of(t),
        "makers": [x for x in ctx["topics"] if x.kind == "hersteller"],
    })


@router.post("/wissen/{topic_id}/bearbeiten", dependencies=[Depends(check_csrf)])
async def edit_topic(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    form = await request.form()
    name, aliases = kb.clean_name(str(form.get("name") or "")), kb.clean_aliases(str(form.get("aliase") or ""))
    if not kb.key_of(name):
        return _back(t.id, "Name darf nicht leer sein.")
    other = kb.find_topic(db, t.kind, name)
    if other and other.id != t.id:
        return _back(t.id, f"„{other.name}“ gibt es schon.")
    before = f"{t.name} ({', '.join(t.aliases or [])})"
    after = f"{name} ({', '.join(aliases)})"
    if before != after:
        t.name, t.key, t.aliases, t.updated_by, t.updated_at = name, kb.key_of(name), aliases, user.id, utcnow()
        kb.log(db, user, "thema", t.id, t.id, "geändert", before, after)
    return _back(t.id)


@router.post("/wissen/{topic_id}/folgen", dependencies=[Depends(check_csrf)])
async def follow(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    form = await request.form()
    kb.set_follow(db, user, t, str(form.get("aktiv") or "") == "1")
    back = str(form.get("zurueck") or "")
    return RedirectResponse(back if back in ("/wissen", f"/wissen/{t.id}") else f"/wissen/{t.id}", status_code=303)


@router.post("/wissen/{topic_id}/feld/{field}", dependencies=[Depends(check_csrf)])
async def save_field(request: Request, topic_id: int, field: str, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    form = await request.form()
    try:
        kb.save_field(db, user, t, field, {k: form.get(k) for k in ("id", "wert", "menge", "bemerkung")})
    except ValueError as exc:
        return _back(t.id, str(exc))
    return _back(t.id, anchor="#angaben")


@router.post("/wissen/{topic_id}/artikel", dependencies=[Depends(check_csrf)])
async def save_product(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    form = await request.form()
    pid = str(form.get("id") or "")
    try:
        pr = kb.save_product(db, user, t, int(pid) if pid.isdigit() else None, dict(form))
    except ValueError as exc:
        return _back(t.id, str(exc), "#vergleich")
    return _back(t.id, anchor=f"#p{pr.id}")


@router.post("/wissen/artikel/{product_id}/loeschen", dependencies=[Depends(check_csrf)])
def delete_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    pr = db.get(KbProduct, product_id)
    if pr is None:
        raise HTTPException(404, "Artikel nicht gefunden")
    gid = pr.group_id
    kb.delete_product(db, user, pr)
    return _back(gid, anchor="#vergleich")


@router.post("/wissen/{topic_id}/kriterien", dependencies=[Depends(check_csrf)])
async def save_criteria(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    try:
        kb.set_criteria(db, user, t, str((await request.form()).get("kriterien") or ""))
    except ValueError as exc:
        return _back(t.id, str(exc), "#vergleich")
    return _back(t.id, anchor="#vergleich")


@router.post("/wissen/{topic_id}/zustaendig", dependencies=[Depends(check_csrf)])
async def set_owner(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    raw = str((await request.form()).get("benutzer") or "")
    kb.set_owner(db, user, t, int(raw) if raw.isdigit() else None)
    return _back(t.id)


@router.post("/wissen/{topic_id}/angabe", dependencies=[Depends(check_csrf)])
async def save_fact(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    form = await request.form()
    fid = str(form.get("id") or "")
    try:
        kb.save_fact(db, user, t, int(fid) if fid.isdigit() else None, str(form.get("bezeichnung") or ""),
                     str(form.get("wert") or ""))
    except ValueError as exc:
        return _back(t.id, str(exc))
    return _back(t.id, anchor="#angaben")


@router.post("/wissen/eintrag", dependencies=[Depends(check_csrf)])
async def create_entry(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    chosen = form.getlist("themen")
    fallback = str(form.get("vorgabe") or "")
    kind = str(form.get("art") or "")
    text = str(form.get("text") or "")
    ids = chosen if chosen else None
    if ids is None and fallback.isdigit() and not kb.detect(text, kb.topics(db))["topic_ids"]:
        ids = [fallback]  # nichts erkannt: Eintrag gehört zum geöffneten Steckbrief
    try:
        e = kb.create_entry(db, user, text, kind or None, ids, str(form.get("privat") or "") == "1")
    except ValueError as exc:
        return _back(int(fallback) if fallback.isdigit() else None, str(exc))
    kb.apply_suggestions(db, user, e, form)  # angehakt: „als Angabe übernehmen“
    target = int(fallback) if fallback.isdigit() and int(fallback) in e.topic_ids else e.topic_ids[0]
    return _back(target, anchor=f"#e{e.id}")


@router.post("/wissen/eintrag/{entry_id}", dependencies=[Depends(check_csrf)])
async def edit_entry(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _entry(db, entry_id, user)
    form = await request.form()
    back = str(form.get("zurueck") or "")
    back_id = int(back) if back.isdigit() else (e.topic_ids or [None])[0]
    try:
        kb.update_entry(db, user, e, str(form.get("text") or ""), str(form.get("art") or ""), form.getlist("themen"),
                        (str(form.get("privat") or "") == "1") if "privat_feld" in form else None)
    except ValueError as exc:
        return _back(back_id, str(exc))
    return _back(back_id if back_id in e.topic_ids else e.topic_ids[0], anchor=f"#e{e.id}")


@router.post("/wissen/eintrag/{entry_id}/geprueft", dependencies=[Depends(check_csrf)])
async def checked(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _entry(db, entry_id, user)
    kb.mark_checked(db, user, e)
    back = str((await request.form()).get("zurueck") or "")
    return _back(int(back) if back.isdigit() else None, anchor=f"#e{e.id}")


@router.post("/wissen/eintrag/{entry_id}/melden", dependencies=[Depends(check_csrf)])
async def flag(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _entry(db, entry_id, user)
    form = await request.form()
    kb.flag_entry(db, user, e, str(form.get("bemerkung") or ""))
    back = str(form.get("zurueck") or "")
    return _back(int(back) if back.isdigit() else None, anchor=f"#e{e.id}")


@router.get("/wissen/eintrag/{entry_id}/loeschen")
def confirm_delete(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _entry(db, entry_id, user)
    back = f"/wissen/{e.topic_ids[0]}" if e.topic_ids else "/wissen"
    return render(request, "confirm_delete.html", {
        "portal": True, "title": "Eintrag löschen", "name": e.text[:80], "action": f"/wissen/eintrag/{e.id}/loeschen",
        "back": back, "impact": ["der Eintrag bei allen zugeordneten Herstellern und Artikelgruppen, für alle Benutzer "
                                 "(im Verlauf bleibt vermerkt, wer ihn wann gelöscht hat)"]})


@router.post("/wissen/eintrag/{entry_id}/loeschen", dependencies=[Depends(check_csrf)])
async def delete_entry(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _entry(db, entry_id, user)
    first = (e.topic_ids or [None])[0]
    if (await request.form()).get("bestaetigt") != "ja":
        return RedirectResponse(f"/wissen/eintrag/{e.id}/loeschen", status_code=303)
    audit(db, user, "wissen_eintrag_geloescht", "kb_entry", e.id, {"text": e.text[:200]}, client_ip(request))
    kb.delete_entry(db, user, e)
    return _back(first)
