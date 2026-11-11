"""Herstellerwissen: gemeinsames Wissen zu Herstellern und Artikelgruppen.

Einträge schreibt man frei hinein; Art und Zuordnung erkennt das Tool mit festen Regeln (keine KI), die Schreibweise
wird vereinheitlicht (Herstellernamen, Abkürzungen, Satzanfang, Punkt). Alles außer privaten Einträgen ist für alle
sichtbar und änderbar; jede Änderung steht mit Name und Zeitpunkt im Verlauf. Jeder wählt selbst, welchen Themen er
folgt (Standard: allen); nicht gefolgte Themen erscheinen nicht in Übersicht und Suche.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.models.entities import KbChange, KbEntry, KbFact, KbTopic, KbUnfollow, Manufacturer, User, utcnow

KINDS = {"hersteller": "Hersteller", "gruppe": "Artikelgruppe"}
TYPES = {  # Reihenfolge = Reihenfolge im Steckbrief
    "bezug": "Bezugsweg / Bedingung",
    "kalk": "Kalkulation",
    "pflicht": "Pflicht-Zubehör",
    "liefer": "Lieferzeit / Kontakt",
    "hinweis": "Hinweis",
}
STALE_DAYS = 365  # danach „bitte prüfen“
MAX_TEXT, MAX_TOPICS = 1000, 8

# Stichwörter je Art (Reihenfolge: spätere gewinnen, „braucht“ schlägt „Aufschlag“)
_RULES = [
    ("liefer", r"lieferzeit|\bwochen?\b|\btage?\b|\bkw\s?\d|ansprech|kontakt|telefon|\btel\.|e-?mail|@"),
    ("bezug", r"\bmoq\b|mindest|\bmind\.|\bab \d+\s?(st|stk|stück)|nur über|über \w+ (bestellen|beziehen|anfragen)|"
              r"bestellen bei|beziehen|anfragen|lagerartikel|nicht (auf|am) lager|auf bestellung"),
    ("kalk", r"kalkul|aufschlag|faktor|marge|rabatt|teurer|günstiger|preis|\d\s?%|mehr verlangen|\bvk\b|\bek\b"),
    ("pflicht", r"brauch|benötig|unbedingt|pflicht|nur mit|immer mit|immer (den|die|das)|zwingend|muss .* dazu"),
]
_ABBREV = [
    (r"\bstk\.?(?=\W|$)", "Stück"),
    (r"\bstück\b", "Stück"),
    (r"\bmoq\b", "Mindestbestellmenge"),
    (r"\bmind\.(?=\s)", "mindestens"),
    (r"\bz\.\s?b\.?(?=\s|$)|\bzb\.?(?=\s|$)", "z. B."),
    (r"\binkl\.?(?=\s)", "inklusive"),
    (r"\bexkl\.?(?=\s)", "exklusive"),
    (r"\bca(?=\s\d)", "ca."),
]


def key_of(name: str) -> str:
    """Vergleichsschlüssel: Kleinbuchstaben, ohne Akzente, Leer- und Sonderzeichen („Nordic-Lights“ = „nordic lights“)."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)[:120]


def clean_name(name: str) -> str:
    return " ".join(str(name or "").split())[:120]


def clean_aliases(raw) -> list[str]:
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    out = []
    for a in items:
        a = clean_name(a)[:60]
        if a and key_of(a) and a.lower() not in [x.lower() for x in out]:
            out.append(a)
    return out[:10]


# ---------- Themen ----------

def topics(db: Session) -> list[KbTopic]:
    return list(db.scalars(select(KbTopic).order_by(KbTopic.kind, KbTopic.name)))


def find_topic(db: Session, kind: str, name: str) -> KbTopic | None:
    return db.scalar(select(KbTopic).where(KbTopic.kind == kind, KbTopic.key == key_of(name)))


def create_topic(db: Session, user: User | None, kind: str, name: str, aliases=None) -> KbTopic:
    name = clean_name(name)
    if kind not in KINDS or not key_of(name):
        raise ValueError("Art und Name angeben")
    existing = find_topic(db, kind, name)
    if existing:
        return existing
    t = KbTopic(kind=kind, name=name, key=key_of(name), aliases=clean_aliases(aliases),
                created_by=user.id if user else None, updated_by=user.id if user else None)
    db.add(t)
    db.flush()
    log(db, user, "thema", t.id, t.id, "angelegt", None, f"{KINDS[kind]}: {name}")
    return t


def sync_manufacturers(db: Session) -> int:
    """Gemeinsame Herstellerliste: jeder Hersteller aus den Preislisten aller Benutzer erscheint einmal (über den Namen
    zugeordnet, Aliase werden übernommen). Gibt die Zahl neu angelegter Hersteller zurück."""
    known = {t.key: t for t in db.scalars(select(KbTopic).where(KbTopic.kind == "hersteller"))}
    alias_keys = {key_of(a) for t in known.values() for a in t.aliases or []}
    new = 0
    for m in db.scalars(select(Manufacturer).order_by(Manufacturer.created_at)):
        k = key_of(m.name)
        if not k or k in alias_keys:
            continue
        if k in known:
            t = known[k]
            merged = clean_aliases((t.aliases or []) + list(m.aliases or []))
            if merged != (t.aliases or []):
                t.aliases = merged
            continue
        t = KbTopic(kind="hersteller", name=clean_name(m.name), key=k, aliases=clean_aliases(m.aliases or []))
        db.add(t)
        known[k] = t
        new += 1
    if new:
        db.flush()
    return new


def own_manufacturers(db: Session, topic: KbTopic, user: User) -> list[Manufacturer]:
    """Hersteller der eigenen Preisliste, die zu diesem Thema gehören (Name oder Alias gleich)."""
    if topic.kind != "hersteller":
        return []
    keys = {topic.key, *(key_of(a) for a in topic.aliases or [])}
    rows = db.scalars(select(Manufacturer).where(Manufacturer.owner_id == user.id))
    return [m for m in rows if key_of(m.name) in keys or any(key_of(a) in keys for a in m.aliases or [])]


def unfollowed(db: Session, user: User) -> set[int]:
    return set(db.scalars(select(KbUnfollow.topic_id).where(KbUnfollow.user_id == user.id)))


def set_follow(db: Session, user: User, topic: KbTopic, on: bool) -> None:
    row = db.get(KbUnfollow, (user.id, topic.id))
    if on and row:
        db.delete(row)
    elif not on and not row:
        db.add(KbUnfollow(user_id=user.id, topic_id=topic.id))


# ---------- Erkennung und Schreibweise (ohne KI) ----------

def _names(topic: KbTopic) -> list[str]:
    return sorted({topic.name, *(topic.aliases or [])}, key=len, reverse=True)


def _pattern(names: list[str]) -> re.Pattern:
    parts = [r"\s*[-\s]?\s*".join(re.escape(w) for w in n.split()) for n in names if n.strip()]
    return re.compile(r"(?<![\wäöüß])(" + "|".join(parts) + r")(?![\wäöüß])", re.IGNORECASE)


def detect(text: str, all_topics: list[KbTopic]) -> dict:
    """Art und Themen aus dem freien Text. Themen: Name oder Alias kommt vor (Groß-/Kleinschreibung egal)."""
    low = (text or "").lower()
    kind = "hinweis"
    for t, rx in _RULES:
        if re.search(rx, low):
            kind = t
    found = [t.id for t in all_topics if _pattern(_names(t)).search(text or "")]
    return {"type": kind, "topic_ids": found[:MAX_TOPICS]}


def tidy(text: str, all_topics: list[KbTopic]) -> str:
    """Einheitliche Schreibweise: Leerzeichen, Abkürzungen ausgeschrieben, Herstellernamen wie im Steckbrief,
    bekannte Artikelgruppen groß, Zahl und Einheit getrennt, großer Satzanfang, Punkt am Ende. Zahlen bleiben."""
    t = " ".join(str(text or "").split())[:MAX_TEXT]
    for rx, repl in _ABBREV:
        t = re.sub(rx, repl, t, flags=re.IGNORECASE)
    for topic in all_topics:
        if topic.kind == "hersteller":
            t = _pattern(_names(topic)).sub(topic.name, t)
        else:
            t = _pattern(_names(topic)).sub(lambda m: m.group(1)[:1].upper() + m.group(1)[1:], t)
    t = re.sub(r"(\d)(mm|cm|m|kg|w|v|stk)\b", lambda m: m.group(1) + " " + m.group(2), t, flags=re.IGNORECASE)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    if t:
        t = t[0].upper() + t[1:]
        if t[-1] not in ".!?:":
            t += "."
    return t


# ---------- Einträge ----------

def can_see(entry: KbEntry, user: User) -> bool:
    return not entry.private or entry.author_id == user.id


def visible_entries(db: Session, user: User):
    return select(KbEntry).where(or_(KbEntry.private.is_(False), KbEntry.author_id == user.id))


def entries_for(db: Session, user: User, topic_id: int) -> list[KbEntry]:
    rows = db.scalars(visible_entries(db, user).order_by(KbEntry.updated_at.desc()))
    return [e for e in rows if topic_id in (e.topic_ids or [])]


def valid_topic_ids(db: Session, ids) -> list[int]:
    wanted = []
    for i in ids or []:
        try:
            wanted.append(int(i))
        except (TypeError, ValueError):
            continue
    existing = set(db.scalars(select(KbTopic.id).where(KbTopic.id.in_(wanted))))
    return list(dict.fromkeys(i for i in wanted if i in existing))[:MAX_TOPICS]


def _snapshot(e: KbEntry) -> str:
    return json.dumps({"art": e.type, "text": e.text, "themen": e.topic_ids, "privat": e.private}, ensure_ascii=False)


def create_entry(db: Session, user: User, text: str, kind: str | None, topic_ids, private: bool) -> KbEntry:
    all_topics = topics(db)
    original = " ".join(str(text or "").split())[:MAX_TEXT]
    if not original:
        raise ValueError("Bitte etwas eintragen.")
    found = detect(original, all_topics)
    ids = valid_topic_ids(db, topic_ids) if topic_ids is not None else found["topic_ids"]
    if not ids:
        raise ValueError("Bitte mindestens einen Hersteller oder eine Artikelgruppe zuordnen.")
    now = utcnow()
    e = KbEntry(type=kind if kind in TYPES else found["type"], text=tidy(original, all_topics), original=original,
                private=bool(private), author_id=user.id, updated_by=user.id, checked_by=user.id, topic_ids=ids,
                created_at=now, updated_at=now, checked_at=now)
    db.add(e)
    db.flush()
    log(db, user, "eintrag", e.id, ids[0], "angelegt", None, _snapshot(e))
    return e


def update_entry(db: Session, user: User, e: KbEntry, text: str, kind: str, topic_ids, private: bool | None) -> None:
    before = _snapshot(e)
    all_topics = topics(db)
    new_text = " ".join(str(text or "").split())[:MAX_TEXT]
    if not new_text:
        raise ValueError("Der Text darf nicht leer sein.")
    ids = valid_topic_ids(db, topic_ids)
    if not ids:
        raise ValueError("Bitte mindestens einen Hersteller oder eine Artikelgruppe zuordnen.")
    e.text = tidy(new_text, all_topics)
    e.type = kind if kind in TYPES else e.type
    e.topic_ids = ids
    if private is not None and e.author_id == user.id:  # privat schalten darf nur der Ersteller
        e.private = bool(private)
    after = _snapshot(e)
    if after != before:
        e.updated_by, e.updated_at = user.id, utcnow()
        e.checked_by, e.checked_at = user.id, utcnow()
        log(db, user, "eintrag", e.id, ids[0], "geändert", before, after)


def mark_checked(db: Session, user: User, e: KbEntry) -> None:
    e.checked_by, e.checked_at = user.id, utcnow()
    log(db, user, "eintrag", e.id, (e.topic_ids or [None])[0], "geprüft", None, None)


def delete_entry(db: Session, user: User, e: KbEntry) -> None:
    log(db, user, "eintrag", e.id, (e.topic_ids or [None])[0], "gelöscht", _snapshot(e), None)
    db.delete(e)


def is_stale(e: KbEntry, now: datetime | None = None) -> bool:
    return (now or utcnow()) - e.checked_at > timedelta(days=STALE_DAYS)


# ---------- Angaben (Steckbrief) ----------

def save_fact(db: Session, user: User, topic: KbTopic, fact_id: int | None, label: str, value: str) -> KbFact | None:
    label, value = clean_name(label)[:60], " ".join(str(value or "").split())[:200]
    fact = db.get(KbFact, fact_id) if fact_id else None
    if fact and fact.topic_id != topic.id:
        fact = None
    if fact and not (label and value):  # leer = Angabe entfernen
        log(db, user, "angabe", fact.id, topic.id, "gelöscht", f"{fact.label}: {fact.value}", None)
        db.delete(fact)
        return None
    if not (label and value):
        raise ValueError("Bezeichnung und Wert angeben.")
    if fact:
        before = f"{fact.label}: {fact.value}"
        if before != f"{label}: {value}":
            fact.label, fact.value, fact.updated_by, fact.updated_at = label, value, user.id, utcnow()
            log(db, user, "angabe", fact.id, topic.id, "geändert", before, f"{label}: {value}")
        return fact
    pos = len(list(db.scalars(select(KbFact.id).where(KbFact.topic_id == topic.id))))
    fact = KbFact(topic_id=topic.id, label=label, value=value, position=pos, updated_by=user.id)
    db.add(fact)
    db.flush()
    log(db, user, "angabe", fact.id, topic.id, "angelegt", None, f"{label}: {value}")
    return fact


# ---------- Verlauf, Verknüpfungen, Suche ----------

def log(db: Session, user: User | None, obj: str, obj_id: int, topic_id: int | None, action: str,
        before: str | None, after: str | None) -> None:
    db.add(KbChange(object=obj, object_id=obj_id, topic_id=topic_id, user_id=user.id if user else None,
                    action=action, before=before, after=after))


def history(db: Session, obj: str, obj_id: int) -> list[KbChange]:
    return list(db.scalars(select(KbChange).where(KbChange.object == obj, KbChange.object_id == obj_id)
                           .order_by(KbChange.at.desc(), KbChange.id.desc())))


def neighbours(entries: list[KbEntry], topic_id: int) -> list[tuple[int, str, int]]:
    """Themen, die über Einträge mit diesem verbunden sind: (Thema, wichtigste Art, Anzahl Einträge)."""
    weight = {"pflicht": 3, "bezug": 2, "kalk": 1, "liefer": 0, "hinweis": 0}
    out: dict[int, list] = {}
    for e in entries:
        for t in e.topic_ids or []:
            if t == topic_id:
                continue
            cur = out.setdefault(t, [e.type, 0])
            cur[1] += 1
            if weight[e.type] > weight[cur[0]]:
                cur[0] = e.type
    return [(t, k, n) for t, (k, n) in out.items()]


def graph(center: KbTopic, near: list[tuple[KbTopic, str, int]]) -> dict:
    """Positionen für das Verknüpfungsbild (SVG, 640 × H): Mitte = Thema, außen im Kreis die verbundenen."""
    import math

    near = near[:10]
    W, H = 640, 300 if len(near) <= 4 else 380
    cx, cy = W / 2, H / 2
    nodes = []
    for i, (t, kind, n) in enumerate(near):
        a = -math.pi / 2 + i * 2 * math.pi / max(len(near), 1)
        nodes.append({"id": t.id, "name": t.name, "sub": f"{TYPES[kind].split(' /')[0]} · {n}", "kind": kind,
                      "x": round(cx + math.cos(a) * (W / 2 - 115), 1), "y": round(cy + math.sin(a) * (H / 2 - 32), 1),
                      "w": min(220, max(120, len(t.name) * 8 + 30))})
    return {"w": W, "h": H, "cx": cx, "cy": cy, "center": {"name": center.name, "sub": KINDS[center.kind],
                                                             "w": min(240, max(130, len(center.name) * 9 + 30))},
            "nodes": nodes}


def search(db: Session, user: User, q: str, limit: int = 30) -> list[dict]:
    """Suche in Themen (Name, Alias), Angaben und Einträgen; nur gefolgte Themen."""
    q = " ".join(str(q or "").split())[:80]
    if not q:
        return []
    hidden = unfollowed(db, user)
    tops = {t.id: t for t in topics(db) if t.id not in hidden}
    low, k = q.lower(), key_of(q)
    hits = []
    for t in tops.values():
        if (k and (k in t.key or any(k in key_of(a) for a in t.aliases or []))) or low in t.name.lower():
            hits.append({"url": f"/wissen/{t.id}", "title": t.name, "sub": KINDS[t.kind], "rank": 0})
    for f in db.scalars(select(KbFact).where(KbFact.topic_id.in_(list(tops)))):
        if low in f"{f.label} {f.value}".lower():
            hits.append({"url": f"/wissen/{f.topic_id}", "title": f"{f.label}: {f.value}", "sub": tops[f.topic_id].name, "rank": 1})
    for e in db.scalars(visible_entries(db, user).order_by(KbEntry.updated_at.desc())):
        ids = [i for i in e.topic_ids or [] if i in tops]
        if ids and low in f"{e.text} {e.original or ''}".lower():
            hits.append({"url": f"/wissen/{ids[0]}#e{e.id}", "title": e.text,
                         "sub": TYPES[e.type] + " · " + ", ".join(tops[i].name for i in ids), "rank": 2})
    hits.sort(key=lambda h: h["rank"])
    return hits[:limit]
