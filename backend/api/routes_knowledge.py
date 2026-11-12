"""Modul „Vertriebswissen“: gemeinsames Wissen zu Herstellern und Artikelgruppen."""

from __future__ import annotations

import json
import re
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


def _ret(value: str, fallback_id: int | None, error: str | None = None, anchor: str = "") -> RedirectResponse:
    """Zurück dorthin, wo gearbeitet wurde: „start:ID“ = Startseite mit Infofenster von ID, sonst Steckbrief."""
    if value.startswith("start:") and value[6:].isdigit():
        url = f"/wissen?t={value[6:]}" + ("&fehler=" + quote(error) if error else "")
        return RedirectResponse(url + anchor, status_code=303)
    m = re.fullmatch(r"kombi:(\d+):(\d+)", value)
    if m:
        url = f"/wissen?f={m.group(1)}&g={m.group(2)}" + ("&fehler=" + quote(error) if error else "")
        return RedirectResponse(url + anchor, status_code=303)
    return _back(int(value) if value.isdigit() else fallback_id, error, anchor)


def _side_rows(topics: list[KbTopic]) -> list[tuple[KbTopic, int, int | None]]:
    """Herstellerliste links: Firmengruppen zusammen (Mutter, darunter eingerückt die Töchter), Farbe wie auf der Karte."""
    by_id = {t.id: t for t in topics}
    groups = kb.company_groups(by_id)
    color = {rid: i % 6 for i, rid in enumerate(groups)}
    member = {m.id for ms in groups.values() for m in ms[1:]}
    rows = []
    for t in sorted((t for t in topics if t.kind == "hersteller" and t.id not in member), key=lambda x: x.name.lower()):
        rows.append((t, 0, color.get(t.id)))
        rows += [(m, 1, color[t.id]) for m in groups.get(t.id, [])[1:]]
    return rows


def _panel(db: Session, user: User, ctx: dict, t: KbTopic) -> dict:
    """Infofenster rechts: alles Wichtige zu einem Hersteller/einer Gruppe als Liste."""
    by_id = {x.id: x for x in ctx["topics"]}
    entries = kb.entries_for(db, user, t.id)
    fields = kb.field_facts(db, t.id)
    incoming = list(db.scalars(select(KbFact).where(KbFact.ref_topic_id == t.id)))
    groups = kb.company_groups(by_id)
    root = kb.root_of(t, by_id)
    rule = kb.rule_of(fields, by_id) if t.kind == "hersteller" else None
    if t.kind == "gruppe":
        products = kb.group_products(db, t)
    else:
        products = kb.maker_products(db, t, by_id)
    return {"p_topic": t, "p_entries": entries,
            "p_grouped": [(k, label, [e for e in entries if e.type == k]) for k, label in kb.TYPES.items()],
            "p_fields": fields, "p_facts": kb.free_facts(db, t.id), "p_rule": rule,
            "p_rule_text": kb.rule_conditions(rule) if rule and rule.get("via") else None,
            "p_incoming": [(by_id[f.topic_id], _incoming_text(db, f, by_id)) for f in incoming if f.topic_id in by_id],
            "p_company": groups.get(root.id, []), "p_root": root, "p_products": products,
            "p_following": t.id not in ctx["hidden"], "field_defs": kb.FIELDS, "describe": kb.describe,
            "fact_stale": kb.fact_stale, "by_id": by_id, "p_keys": kb.FIELDS_BY_KIND[t.kind],
            "p_rel": kb.relations(db, user, t, by_id),
            "p_assigned": sorted((by_id[i] for i in kb.assortment_of(db, t) if i in by_id), key=lambda x: x.name.lower()),
            "p_options": [x for x in ctx["topics"] if x.kind == {"hersteller": "gruppe", "gruppe": "hersteller"}.get(t.kind)
                          and x.id not in kb.assortment_of(db, t)],
            **_series_ctx(db, user, ctx, t, by_id)}


def _series_ctx(db: Session, user: User, ctx: dict, t: KbTopic, by_id: dict) -> dict:
    """Serien: bei Gruppe/Hersteller die Liste, bei einer Serie Gruppe, Hersteller und was für beide allgemein gilt."""
    tops = ctx["topics"]
    makers = [x for x in tops if x.kind == "hersteller"]
    groups = [x for x in tops if x.kind == "gruppe"]
    if t.kind == "serie":
        g, m = by_id.get(t.parent_id), by_id.get(t.maker_id)
        return {"s_group": g, "s_maker": m, "s_makers": makers, "s_groups": groups,
                "s_pair": kb.pair_info(db, user, m, g, by_id) if g and m else None,
                "rule_conditions": kb.rule_conditions}
    series = kb.series_of(tops, group=t if t.kind == "gruppe" else None, maker=t if t.kind == "hersteller" else None)
    return {"p_series": series, "s_makers": makers, "s_groups": groups,
            "s_counts": {x.id: len(kb.entries_for(db, user, x.id)) for x in series}}


def _pair(db: Session, user: User, ctx: dict, f: KbTopic, g: KbTopic) -> dict:
    by_id = {x.id: x for x in ctx["topics"]}
    info = kb.pair_info(db, user, f, g, by_id)
    series = kb.series_of(ctx["topics"], group=g, maker=f)
    return {"pair": info, "pf": f, "pg": g, "by_id": by_id, "describe": kb.describe, "p_series": series,
            "s_counts": {x.id: len(kb.entries_for(db, user, x.id)) for x in series},
            "rel_f": kb.relations(db, user, f, by_id), "rel_g": kb.relations(db, user, g, by_id),
            "assigned": g.id in kb.assortment_of(db, f), "asg_f": kb.assortment_of(db, f), "asg_g": kb.assortment_of(db, g),
            "rule_conditions": kb.rule_conditions}


def _selection(db: Session, t: int | None, f: int | None, g: int | None) -> tuple:
    """(Firma, Artikelgruppe) aus den Adressparametern; t = einzelnes Thema beliebiger Art."""
    def get(i, kind):
        x = db.get(KbTopic, i) if i else None
        return x if x and (kind is None or x.kind == kind) else None
    one = get(t, None)
    fx, gx = get(f, "hersteller"), get(g, None)
    if gx and gx.kind not in ("gruppe", "serie"):
        gx = None
    if one:
        fx, gx = (one, gx) if one.kind == "hersteller" else (fx, one)
    return fx, gx


def _overview(db: Session, user: User, ctx: dict) -> dict:
    hidden, by_id = ctx["hidden"], {t.id: t for t in ctx["topics"]}
    followed = [e for e in db.scalars(kb.visible_entries(db, user).order_by(KbEntry.updated_at.desc()))
                if any(t not in hidden for t in e.topic_ids or [])]
    return {"recent": followed[:15], "attention": kb.attention(db, user), "by_id": by_id}


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
    return {"portal": True, "wide": True, "full": True, "topics": all_topics, "hidden": hidden, "names": names, "counts": counts, "pcounts": pcounts,
            "types": kb.TYPES, "kinds": kb.KINDS, "error": error, "is_stale": kb.is_stale, "due_date": kb.due_date,
            "topic_json": json.dumps([{"id": t.id, "name": t.name, "kind": kb.KINDS[t.kind]} for t in all_topics],
                                     ensure_ascii=False)}


def _incoming_text(db: Session, f: KbFact, by_id: dict) -> str:
    """Was ein anderes Thema über dieses festlegt, aus Sicht dieses Themas."""
    src = by_id[f.topic_id].name
    if f.field == "bezug_klein":
        r = kb.rule_of(kb.field_facts(db, f.topic_id), by_id)
        return kb.reverse_rule_text(by_id[f.topic_id], r) if r else f"Für {src}: kleine Mengen kommen hierher"
    if f.field == "pflicht":
        return f"Pflicht-Zubehör für {src} ({f.number or 1} × je Artikel)"
    return f"{src}: {f.label}"


@router.get("/wissen")
def overview(request: Request, fehler: str | None = None, neu: str | None = None, t: int | None = None,
             f: int | None = None, g: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ctx = _context(db, user, fehler)
    fx, gx = _selection(db, t, f, g)
    att = kb.attention(db, user)
    flagged = {i for e in att["mine"] + att["other"] for i in e.topic_ids or []}
    if gx and gx.kind == "serie":
        extra = _panel(db, user, ctx, gx)
    elif fx and gx:
        extra = _pair(db, user, ctx, fx, gx)
    elif fx or gx:
        extra = _panel(db, user, ctx, fx or gx)
    else:
        extra = {}
    return render(request, "knowledge.html", {**ctx, **_overview(db, user, ctx), **extra, "topic": None,
                                              "sel": fx or gx, "sel_f": fx, "sel_g": gx,
                                              "side_rows": _side_rows(ctx["topics"]), "flagged": flagged,
                                              "prefill": (neu or "")[:200]})


@router.post("/wissen/sortiment", dependencies=[Depends(check_csrf)])
async def assortment(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Artikelgruppe einem Hersteller zuordnen oder lösen (aus Infofenster, Liste oder Steckbrief)."""
    form = await request.form()
    back = str(form.get("zurueck") or "")
    m, g = str(form.get("hersteller") or ""), str(form.get("gruppe") or "")
    if not (m.isdigit() and g.isdigit()):
        return _ret(back, None, "Bitte einen Hersteller und eine Artikelgruppe wählen.")
    maker, group = _topic(db, int(m)), _topic(db, int(g))
    try:
        kb.set_assortment(db, user, maker, group, form.get("aktion") != "entfernen")
    except ValueError as exc:
        return _ret(back, maker.id, str(exc))
    return _ret(back, maker.id)


@router.get("/wissen/karteninfo")
def map_card(request: Request, f: int | None = None, g: int | None = None, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    """Infofeld auf der Karte: nur Hersteller (Standard-Infos), nur Artikelgruppe (alles zur Gruppe, nach Herstellern
    sortiert), Hersteller → Gruppe (Kombination)."""
    ctx = _context(db, user, None)
    by_id = {x.id: x for x in ctx["topics"]}
    fx, gx = _selection(db, None, f, g)
    data: dict = {"cf": fx, "cg": gx, "by_id": by_id, "rule_conditions": kb.rule_conditions}
    if gx and gx.kind == "serie":
        e = kb.entries_for(db, user, gx.id)
        fields = kb.field_facts(db, gx.id)
        data.update(mode="serie", series=gx, s_group=by_id.get(gx.parent_id), s_maker=by_id.get(gx.maker_id),
                    s_facts=[(kb.FIELDS[k][0], kb.describe(x, by_id)) for k in kb.FIELDS_BY_KIND["serie"] for x in fields.get(k, [])]
                    + [(x.label, x.value) for x in kb.free_facts(db, gx.id)], types=kb._by_type(e), count=len(e))
    elif fx and gx:
        data.update(mode="pair", P=kb.pair_info(db, user, fx, gx, by_id), series=kb.series_of(ctx["topics"], gx, fx),
                    assigned=gx.id in kb.assortment_of(db, fx))
    elif fx:
        data.update(mode="maker", C=kb.maker_card(db, user, fx, by_id))
    elif gx:
        data.update(mode="group", C=kb.group_card(db, user, gx, by_id))
    else:
        raise HTTPException(404, "Nicht gefunden")
    return render(request, "knowledge_mapcard.html", {**ctx, **data})


@router.get("/wissen/kombi")
def pair_panel(request: Request, f: int, g: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ctx = _context(db, user, None)
    fx, gx = _selection(db, None, f, g)
    if not (fx and gx):
        raise HTTPException(404, "Nicht gefunden")
    if gx.kind == "serie":
        return render(request, "knowledge_panel.html", {**ctx, **_panel(db, user, ctx, gx), "sel": gx})
    return render(request, "knowledge_panel.html", {**ctx, **_pair(db, user, ctx, fx, gx), "sel": fx, "sel_f": fx, "sel_g": gx})


@router.post("/wissen/serie", dependencies=[Depends(check_csrf)])
async def save_series(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Serie anlegen (bei Artikelgruppe/Hersteller) oder ihre Gruppe und ihren Hersteller ändern."""
    form = await request.form()
    back = str(form.get("zurueck") or "")
    g, m, sid = str(form.get("gruppe") or ""), str(form.get("hersteller") or ""), str(form.get("id") or "")
    if not (g.isdigit() and m.isdigit()):
        return _ret(back, None, "Bitte Artikelgruppe und Hersteller wählen.")
    group, maker = _topic(db, int(g)), _topic(db, int(m))
    series = _topic(db, int(sid)) if sid.isdigit() else None
    if series is not None and series.kind != "serie":
        raise HTTPException(404, "Nicht gefunden")
    try:
        x = kb.save_series(db, user, str(form.get("name") or (series.name if series else "")), group, maker,
                           [a for a in str(form.get("aliase") or "").split(",")], series)
    except ValueError as exc:
        return _ret(back, group.id, str(exc))
    return _ret(back if back else f"start:{x.id}", x.id)


@router.get("/wissen/ueberblick")
def overview_panel(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ctx = _context(db, user, None)
    return render(request, "knowledge_panel.html", {**ctx, **_overview(db, user, ctx), "sel": None})


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
    groups = kb.company_groups(by_id)
    root = kb.root_of(t, by_id)
    company = [m for m in groups.get(root.id, [])]
    near = [(by_id[i], kind, n) for i, kind, n in kb.neighbours(entries, t.id, links, related, [m.id for m in company])
            if i in by_id]
    histories = {e.id: kb.history(db, "eintrag", e.id) for e in entries}
    changes = list(db.scalars(select(KbChange).where(KbChange.topic_id == t.id).order_by(KbChange.at.desc()).limit(15)))
    return render(request, "knowledge.html", {
        **ctx, "topic": t, "grouped": grouped, "entries": entries, "facts": facts, "by_id": by_id,
        "fields": fields, "field_defs": kb.FIELDS, "field_keys": kb.FIELDS_BY_KIND[t.kind], "lager_choices": kb.LAGER_CHOICES,
        "describe": kb.describe, "fact_stale": kb.fact_stale, "due_date": kb.due_date,
        "rule": kb.rule_of(fields, by_id) if t.kind == "hersteller" else None, "rule_conditions": kb.rule_conditions,
        "users": [u for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.username))],
        "referenced_by": [(by_id[f.topic_id], _incoming_text(db, f, by_id)) for f in incoming if f.topic_id in by_id],
        "graph": kb.graph(t, near) if near else None, "histories": histories, "changes": changes,
        "own": kb.own_manufacturers(db, t, user), "following": t.id not in ctx["hidden"], "is_stale": kb.is_stale,
        "compare": compare, "maker_rows": maker_rows, "criteria": kb.criteria_of(t),
        "company": company, "company_root": root, "children": [x for x in ctx["topics"] if x.parent_id == t.id],
        "makers": [x for x in ctx["topics"] if x.kind == "hersteller"],
    })


@router.get("/wissen/{topic_id}/kurz")
def topic_panel(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ctx = _context(db, user, None)
    t = _topic(db, topic_id)
    return render(request, "knowledge_panel.html", {**ctx, **_panel(db, user, ctx, t), "sel": t})


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
    ok = back in ("/wissen", f"/wissen/{t.id}") or (back.startswith("/wissen?t=") and back[10:].isdigit())
    return RedirectResponse(back if ok else f"/wissen/{t.id}", status_code=303)


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


@router.post("/wissen/{topic_id}/bezugsregel", dependencies=[Depends(check_csrf)])
async def save_rule(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Bezugsregel in einem Schritt: ab Menge / oder Lagerware hier bestellen, sonst beim gewählten Händler."""
    t = _topic(db, topic_id)
    form = await request.form()
    try:
        if form.get("aktion") == "entfernen":
            kb.delete_rule(db, user, t)
        else:
            kb.save_rule(db, user, t, str(form.get("moq") or ""), str(form.get("lagerware") or "") == "1",
                         str(form.get("via") or ""), " ".join(str(form.get("notiz") or "").split())[:200])
    except ValueError as exc:
        return _back(t.id, str(exc), "#regel")
    return _back(t.id, anchor="#regel")


@router.post("/wissen/{topic_id}/firmengruppe", dependencies=[Depends(check_csrf)])
async def set_parent(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Muttergesellschaft setzen/lösen („mutter“) oder eine Tochterfirma hinzufügen/lösen („tochter“, „loesen“)."""
    t = _topic(db, topic_id)
    form = await request.form()
    try:
        if "tochter" in form:
            child = _topic(db, int(form["tochter"])) if str(form["tochter"]).isdigit() else None
            if child is None:
                raise ValueError("Bitte eine Firma wählen.")
            kb.set_parent(db, user, child, None if form.get("loesen") == "1" else t.id)
        else:
            raw = str(form.get("mutter") or "")
            kb.set_parent(db, user, t, int(raw) if raw.isdigit() else None)
    except ValueError as exc:
        return _back(t.id, str(exc), "#firmengruppe")
    return _back(t.id, anchor="#firmengruppe")


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
        if str(form.get("ziel") or "").startswith("kombi:"):
            return _ret(str(form.get("ziel")), None, str(exc))
        if form.get("ziel") == "start" and fallback.isdigit():
            return _ret("start:" + fallback, None, str(exc))
        return _back(int(fallback) if fallback.isdigit() else None, str(exc))
    kb.apply_suggestions(db, user, e, form)  # angehakt: „als Angabe übernehmen“
    target = int(fallback) if fallback.isdigit() and int(fallback) in e.topic_ids else e.topic_ids[0]
    if str(form.get("ziel") or "").startswith("kombi:"):  # aus dem Fenster „Firma × Artikelgruppe“
        return _ret(str(form.get("ziel")), None, anchor=f"#e{e.id}")
    if form.get("ziel") == "start":  # aus dem Infofenster der Startseite
        return _ret(f"start:{target}", None, anchor=f"#e{e.id}")
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
    return _ret(back, None, anchor=f"#e{e.id}")


@router.post("/wissen/eintrag/{entry_id}/melden", dependencies=[Depends(check_csrf)])
async def flag(request: Request, entry_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _entry(db, entry_id, user)
    form = await request.form()
    kb.flag_entry(db, user, e, str(form.get("bemerkung") or ""))
    back = str(form.get("zurueck") or "")
    return _ret(back, None, anchor=f"#e{e.id}")


@router.get("/wissen/{topic_id}/loeschen")
def confirm_delete_topic(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    blocked, impact = kb.topic_delete_impact(db, user, t)
    return render(request, "confirm_delete.html", {
        "portal": True, "title": f"{kb.KINDS[t.kind]} löschen", "name": t.name, "action": f"/wissen/{t.id}/loeschen",
        "back": "/wissen", "blocked": blocked, "impact": impact})


@router.post("/wissen/{topic_id}/loeschen", dependencies=[Depends(check_csrf)])
async def delete_topic(request: Request, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _topic(db, topic_id)
    if (await request.form()).get("bestaetigt") != "ja":
        return RedirectResponse(f"/wissen/{t.id}/loeschen", status_code=303)
    blocked, _impact = kb.topic_delete_impact(db, user, t)
    if blocked:
        return RedirectResponse(f"/wissen/{t.id}/loeschen", status_code=303)
    audit(db, user, "wissen_thema_geloescht", "kb_topic", t.id, {"art": t.kind, "name": t.name}, client_ip(request))
    kb.delete_topic(db, user, t)
    return RedirectResponse("/wissen", status_code=303)


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
