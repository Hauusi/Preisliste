"""Vertriebswissen: gemeinsames Wissen zu Herstellern und Artikelgruppen.

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

from backend.models.entities import (KbChange, KbEntry, KbFact, KbSearchMiss, KbSynonym, KbTopic, KbUnfollow, Manufacturer,
                                     User, utcnow)

KINDS = {"hersteller": "Hersteller", "gruppe": "Artikelgruppe"}
TYPES = {  # Reihenfolge = Reihenfolge im Steckbrief
    "bezug": "Bezugsweg / Bedingung",
    "kalk": "Kalkulation",
    "pflicht": "Pflicht-Zubehör",
    "liefer": "Lieferzeit / Kontakt",
    "hinweis": "Hinweis",
}
# Prüffrist je Art in Tagen: was sich schnell ändert (Lieferzeit, Bezug, Kalkulation), wird früher wieder vorgelegt
STALE_DAYS = {"liefer": 90, "bezug": 180, "kalk": 180, "pflicht": 365, "hinweis": 365}
FACT_STALE_DAYS = 180
MAX_TEXT, MAX_TOPICS = 1000, 8

# Feste Felder im Steckbrief (Schlüssel, Bezeichnung, Eingabeart). „pflicht“ darf mehrfach vorkommen.
FIELDS = {
    "moq": ("Mindestbestellmenge", "menge"),
    "bezug_klein": ("Darunter beziehen über", "thema"),
    "lager": ("Lagerartikel bei uns", "auswahl"),
    "lieferzeit": ("Lieferzeit", "text"),
    "kontakt": ("Ansprechpartner", "text"),
    "pflicht": ("Pflicht-Zubehör", "zubehoer"),
}
FIELDS_BY_KIND = {"hersteller": ["moq", "bezug_klein", "lager", "lieferzeit", "kontakt", "pflicht"],
                  "gruppe": ["moq", "bezug_klein", "lager", "lieferzeit", "pflicht"]}
LAGER_CHOICES = ["ja", "teilweise", "nein"]
HINT_TYPES = ("pflicht", "bezug", "kalk")  # nur das, was beim Anbieten zählt (Hinweise sparsam, sonst weggeklickt)

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
# Häufige Substantive im Vertrieb groß schreiben (nur ganze Wörter, sonst bleibt der Text wie getippt)
_NOUNS = ["Lieferzeit", "Lieferzeiten", "Woche", "Wochen", "Tag", "Tage", "Monat", "Monate", "Kalkulation", "Aufschlag",
          "Rabatt", "Faktor", "Marge", "Preis", "Preise", "Mindestbestellmenge", "Mindestmenge", "Lagerartikel", "Lager",
          "Bestellung", "Anfrage", "Ansprechpartner", "Zubehör", "Montage", "Halter", "Kabel", "Stecker", "Länge"]
_ABBREV += [(r"(?<![\wäöüß])" + n.lower() + r"(?![\wäöüß])", n) for n in _NOUNS]


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
        e.flagged_by = e.flagged_at = e.flag_note = None  # korrigiert: Meldung erledigt
        log(db, user, "eintrag", e.id, ids[0], "geändert", before, after)


def mark_checked(db: Session, user: User, e: KbEntry) -> None:
    e.checked_by, e.checked_at = user.id, utcnow()
    e.flagged_by = e.flagged_at = e.flag_note = None
    log(db, user, "eintrag", e.id, (e.topic_ids or [None])[0], "geprüft", None, None)


def flag_entry(db: Session, user: User, e: KbEntry, note: str) -> None:
    """„Stimmt nicht mehr“: jeder darf melden; der Eintrag wird markiert und steht bei „Bitte prüfen“."""
    note = " ".join(str(note or "").split())[:300] or None
    e.flagged_by, e.flagged_at, e.flag_note = user.id, utcnow(), note
    log(db, user, "eintrag", e.id, (e.topic_ids or [None])[0], "gemeldet", None, note)


def delete_entry(db: Session, user: User, e: KbEntry) -> None:
    log(db, user, "eintrag", e.id, (e.topic_ids or [None])[0], "gelöscht", _snapshot(e), None)
    db.delete(e)


def stale_days(e: KbEntry) -> int:
    return STALE_DAYS.get(e.type, 365)


def is_stale(e: KbEntry, now: datetime | None = None) -> bool:
    """Prüfen nötig: gemeldet oder Prüffrist der Art abgelaufen."""
    return bool(e.flagged_at) or (now or utcnow()) - e.checked_at > timedelta(days=stale_days(e))


def due_date(e: KbEntry) -> datetime:
    return e.checked_at + timedelta(days=stale_days(e))


def set_owner(db: Session, user: User, topic: KbTopic, owner_id: int | None) -> None:
    owner = db.get(User, owner_id) if owner_id else None
    new = owner.id if owner and owner.active else None
    if new != topic.owner_id:
        before = db.get(User, topic.owner_id).username if topic.owner_id and db.get(User, topic.owner_id) else None
        topic.owner_id, topic.updated_by, topic.updated_at = new, user.id, utcnow()
        log(db, user, "thema", topic.id, topic.id, "zuständig", before, owner.username if owner else None)


def attention(db: Session, user: User) -> dict:
    """Was geprüft werden muss: gemeldete und überfällige Einträge (bei gefolgten Themen), getrennt nach
    „meine Zuständigkeit“ und Rest; dazu Themen ohne Zuständigen."""
    hidden = unfollowed(db, user)
    tops = {t.id: t for t in topics(db)}
    mine, other = [], []
    for e in db.scalars(visible_entries(db, user).order_by(KbEntry.checked_at)):
        ids = [i for i in e.topic_ids or [] if i in tops]
        if not is_stale(e) or not any(i not in hidden for i in ids):
            continue
        (mine if any(tops[i].owner_id == user.id for i in ids) else other).append(e)
    key = lambda e: (e.flagged_at is None, e.checked_at)  # gemeldete zuerst
    return {"mine": sorted(mine, key=key), "other": sorted(other, key=key),
            "unowned": [t for t in tops.values() if t.owner_id is None and t.id not in hidden]}


# ---------- Angaben (Steckbrief): feste Felder und freie Angaben ----------

def save_fact(db: Session, user: User, topic: KbTopic, fact_id: int | None, label: str, value: str) -> KbFact | None:
    label, value = clean_name(label)[:60], " ".join(str(value or "").split())[:200]
    fact = db.get(KbFact, fact_id) if fact_id else None
    if fact and (fact.topic_id != topic.id or fact.field):
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


def field_facts(db: Session, topic_id: int) -> dict[str, list[KbFact]]:
    out: dict[str, list[KbFact]] = {}
    for f in db.scalars(select(KbFact).where(KbFact.topic_id == topic_id, KbFact.field.is_not(None)).order_by(KbFact.id)):
        out.setdefault(f.field, []).append(f)
    return out


def free_facts(db: Session, topic_id: int) -> list[KbFact]:
    return list(db.scalars(select(KbFact).where(KbFact.topic_id == topic_id, KbFact.field.is_(None))
                           .order_by(KbFact.position, KbFact.id)))


def describe(f: KbFact, by_id: dict[int, KbTopic]) -> str:
    """Lesbarer Wert eines festen Felds (auch für Verlauf, Suche und Hinweise)."""
    ref = by_id.get(f.ref_topic_id).name if f.ref_topic_id in by_id else ""
    if f.field == "moq":
        return f"{f.number} Stück"
    if f.field == "bezug_klein":
        return ref or f.value
    if f.field == "pflicht":
        return f"{f.number or 1} × {ref}" + (f" ({f.value})" if f.value else "")
    return f.value


def save_field(db: Session, user: User, topic: KbTopic, field: str, form: dict) -> None:
    """Festes Feld setzen oder (leer) entfernen. Pflicht-Zubehör: je Zubehör ein Eintrag (fact_id zum Ändern)."""
    if field not in FIELDS or field not in FIELDS_BY_KIND[topic.kind]:
        raise ValueError("Unbekanntes Feld.")
    label, kind = FIELDS[field]
    by_id = {t.id: t for t in topics(db)}
    existing = field_facts(db, topic.id).get(field, [])
    fid = str(form.get("id") or "")
    fact = next((f for f in existing if str(f.id) == fid), None) if field == "pflicht" else (existing[0] if existing else None)
    raw = " ".join(str(form.get("wert") or "").split())[:200]
    number, ref, value = None, None, raw
    if kind == "menge":
        digits = re.sub(r"[^\d]", "", raw)
        number = int(digits) if digits and int(digits) > 0 else None
        value = str(number) if number else ""
    elif kind == "thema":
        ref = int(raw) if raw.isdigit() and int(raw) in by_id and int(raw) != topic.id else None
        value = by_id[ref].name if ref else ""
    elif kind == "auswahl":
        value = raw if raw in LAGER_CHOICES else ""
    elif kind == "zubehoer":
        ref = int(raw) if raw.isdigit() and int(raw) in by_id and int(raw) != topic.id else None
        qty = re.sub(r"[^\d]", "", str(form.get("menge") or "1"))
        number = max(1, min(int(qty or 1), 999))
        value = " ".join(str(form.get("bemerkung") or "").split())[:120]
        if not ref:
            value = ""
    empty = (not number) if kind == "menge" else (not ref) if kind in ("thema", "zubehoer") else (not value)
    if empty:  # leer = Feld entfernen; Ungültiges melden
        if raw and kind != "text":
            raise ValueError(f"{label}: bitte einen gültigen Wert angeben.")
        if fact:
            log(db, user, "angabe", fact.id, topic.id, "gelöscht", f"{label}: {describe(fact, by_id)}", None)
            db.delete(fact)
        return
    if fact:
        before = describe(fact, by_id)
        fact.value, fact.number, fact.ref_topic_id = value, number, ref
        after = describe(fact, by_id)
        if before != after:
            fact.updated_by, fact.updated_at = user.id, utcnow()
            log(db, user, "angabe", fact.id, topic.id, "geändert", f"{label}: {before}", f"{label}: {after}")
        else:
            fact.updated_by, fact.updated_at = user.id, utcnow()  # bestätigt
        return
    fact = KbFact(topic_id=topic.id, label=label, value=value, number=number, ref_topic_id=ref, field=field,
                  position=list(FIELDS).index(field), updated_by=user.id)
    db.add(fact)
    db.flush()
    log(db, user, "angabe", fact.id, topic.id, "angelegt", None, f"{label}: {describe(fact, by_id)}")


def fact_stale(f: KbFact) -> bool:
    return utcnow() - f.updated_at > timedelta(days=FACT_STALE_DAYS)


def flow(topic: KbTopic, fields: dict[str, list[KbFact]], by_id: dict[int, KbTopic]) -> dict | None:
    """Entscheidungsweg bei kleinen Mengen, aus den festen Feldern gebaut (nur wenn eine Mindestmenge eingetragen ist):
    Menge ≥ Mindestmenge → direkt; sonst Lagerartikel? → aus Lager; sonst → Bezug über …"""
    moq = (fields.get("moq") or [None])[0]
    if not moq or not moq.number:
        return None
    via = (fields.get("bezug_klein") or [None])[0]
    via_t = by_id.get(via.ref_topic_id) if via else None
    lager = ((fields.get("lager") or [None])[0] or None)
    lager = lager.value if lager else None
    small = {"text": f"bei {via_t.name} anfragen" if via_t else "Bezugsweg fehlt – unter „Darunter beziehen über“ eintragen",
             "topic": via_t.id if via_t else None, "missing": not via_t}
    return {"moq": moq.number, "name": topic.name, "lager": lager, "small": small}


# ---------- Hinweise am Arbeitsplatz (Preisliste, Datenblatt) ----------

def topics_for_manufacturer(db: Session, m: Manufacturer) -> list[KbTopic]:
    keys = {key_of(m.name), *(key_of(a) for a in m.aliases or [])}
    return [t for t in db.scalars(select(KbTopic).where(KbTopic.kind == "hersteller"))
            if t.key in keys or any(key_of(a) in keys for a in t.aliases or [])]


def hints(db: Session, user: User, topic_list: list[KbTopic], limit: int = 6) -> list[dict]:
    """Wenige, gezielte Hinweise zu den Themen: Mindestmenge mit Bezugsweg, Pflicht-Zubehör, Lieferzeit (feste
    Felder) und Einträge der Arten Pflicht-Zubehör, Bezugsweg, Kalkulation. Nicht gefolgte Themen bleiben weg."""
    hidden = unfollowed(db, user)
    by_id = {t.id: t for t in topics(db)}
    wanted = [t for t in topic_list if t.id not in hidden]
    out: list[dict] = []
    for t in wanted:
        f = field_facts(db, t.id)
        if f.get("moq"):
            via = by_id.get(f["bezug_klein"][0].ref_topic_id) if f.get("bezug_klein") else None
            out.append({"type": "bezug", "topic": t, "text": f"Mindestbestellmenge {f['moq'][0].number} Stück"
                        + (f", darunter über {via.name}" if via else ""), "url": f"/wissen/{t.id}"})
        for p in f.get("pflicht", []):
            out.append({"type": "pflicht", "topic": t, "text": f"Pflicht-Zubehör: {describe(p, by_id)}", "url": f"/wissen/{t.id}"})
        if f.get("lieferzeit"):
            out.append({"type": "liefer", "topic": t, "text": f"Lieferzeit: {f['lieferzeit'][0].value}", "url": f"/wissen/{t.id}"})
    ids = {t.id for t in wanted}
    order = {k: i for i, k in enumerate(HINT_TYPES)}
    entries = [e for e in db.scalars(visible_entries(db, user)) if e.type in HINT_TYPES and ids & set(e.topic_ids or [])]
    entries.sort(key=lambda e: (order[e.type], -e.updated_at.timestamp()))
    for e in entries:
        t = by_id[next(i for i in e.topic_ids if i in ids)]
        out.append({"type": e.type, "topic": t, "text": e.text, "url": f"/wissen/{t.id}#e{e.id}", "stale": is_stale(e)})
    return out[:limit]


def topics_in_text(db: Session, text: str) -> list[KbTopic]:
    by_id = {t.id: t for t in topics(db)}
    return [by_id[i] for i in detect(text, list(by_id.values()))["topic_ids"]]


# ---------- Verlauf, Verknüpfungen ----------

def log(db: Session, user: User | None, obj: str, obj_id: int, topic_id: int | None, action: str,
        before: str | None, after: str | None) -> None:
    db.add(KbChange(object=obj, object_id=obj_id, topic_id=topic_id, user_id=user.id if user else None,
                    action=action, before=before, after=after))


def history(db: Session, obj: str, obj_id: int) -> list[KbChange]:
    return list(db.scalars(select(KbChange).where(KbChange.object == obj, KbChange.object_id == obj_id)
                           .order_by(KbChange.at.desc(), KbChange.id.desc())))


def neighbours(entries: list[KbEntry], topic_id: int, facts: list[KbFact] | None = None) -> list[tuple[int, str, int]]:
    """Themen, die über Einträge oder feste Felder (Bezug über, Pflicht-Zubehör) verbunden sind:
    (Thema, wichtigste Art, Anzahl Verbindungen)."""
    weight = {"pflicht": 3, "bezug": 2, "kalk": 1, "liefer": 0, "hinweis": 0}
    out: dict[int, list] = {}

    def add(t: int, kind: str) -> None:
        cur = out.setdefault(t, [kind, 0])
        cur[1] += 1
        if weight[kind] > weight[cur[0]]:
            cur[0] = kind

    for e in entries:
        for t in e.topic_ids or []:
            if t != topic_id:
                add(t, e.type)
    for f in facts or []:
        if f.ref_topic_id and f.ref_topic_id != topic_id:
            add(f.ref_topic_id, "pflicht" if f.field == "pflicht" else "bezug")
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


# ---------- Suche: Einzelwörter, Synonyme, Suchen ohne Treffer ----------

def synonym_groups(db: Session) -> list[KbSynonym]:
    return list(db.scalars(select(KbSynonym).order_by(KbSynonym.id)))


def save_synonyms(db: Session, user: User, group_id: int | None, raw: str) -> None:
    """Eine Gruppe gleichbedeutender Wörter (Komma getrennt); leer = Gruppe löschen. Mit Name und Zeit im Verlauf."""
    words = clean_aliases(raw)
    group = db.get(KbSynonym, group_id) if group_id else None
    if group and len(words) < 2:
        log(db, user, "synonym", group.id, None, "gelöscht", ", ".join(group.words), None)
        db.delete(group)
        return
    if len(words) < 2:
        raise ValueError("Mindestens zwei Wörter mit Komma trennen, z. B. „MOQ, Mindestbestellmenge“.")
    if group:
        before = ", ".join(group.words)
        group.words, group.updated_by, group.updated_at = words, user.id, utcnow()
        log(db, user, "synonym", group.id, None, "geändert", before, ", ".join(words))
    else:
        group = KbSynonym(words=words, updated_by=user.id)
        db.add(group)
        db.flush()
        log(db, user, "synonym", group.id, None, "angelegt", None, ", ".join(words))
    # Wörter, die jetzt gefunden werden, aus der Liste „ohne Treffer“ nehmen
    keys = {key_of(w) for w in words}
    for miss in db.scalars(select(KbSearchMiss)):
        if set(_tokens(miss.query)) & keys:
            db.delete(miss)


def _tokens(q: str) -> list[str]:
    return [key_of(w) for w in re.split(r"[\s,;/]+", q or "") if key_of(w)]


def expand(db: Session, q: str) -> list[set[str]]:
    """Je Suchwort die Menge gleichbedeutender Schlüssel (Wort selbst plus Synonyme)."""
    groups = [{key_of(w) for w in g.words} for g in synonym_groups(db)]
    out = []
    for tok in _tokens(q)[:8]:
        alts = {tok}
        for g in groups:
            if tok in g:
                alts |= g
        out.append(alts)
    return out


def _match(hay: str, alts_per_word: list[set[str]]) -> bool:
    return all(any(a in hay for a in alts) for alts in alts_per_word)


def search(db: Session, user: User, q: str, limit: int = 30) -> list[dict]:
    """Suche in Themen (Name, andere Schreibweisen), Angaben und Einträgen; nur gefolgte Themen.
    Jedes Suchwort muss vorkommen (Reihenfolge egal), Synonyme zählen mit, Groß-/Kleinschreibung, Umlaute,
    Leerzeichen und Bindestriche egal („nordic moq“ findet „Nordic Lights … Mindestbestellmenge“)."""
    alts = expand(db, q)
    if not alts:
        return []
    hidden = unfollowed(db, user)
    tops = {t.id: t for t in topics(db) if t.id not in hidden}
    by_all = {t.id: t for t in topics(db)}
    hits = []
    for t in tops.values():
        hay = key_of(" ".join([t.name, *(t.aliases or []), KINDS[t.kind]]))
        if _match(hay, alts):
            hits.append({"url": f"/wissen/{t.id}", "title": t.name, "sub": KINDS[t.kind], "rank": 0})
    for f in db.scalars(select(KbFact).where(KbFact.topic_id.in_(list(tops)))):
        shown = describe(f, by_all) if f.field else f.value
        hay = key_of(f"{tops[f.topic_id].name} {f.label} {shown}")
        if _match(hay, alts):
            hits.append({"url": f"/wissen/{f.topic_id}#angaben", "title": f"{f.label}: {shown}",
                         "sub": tops[f.topic_id].name, "rank": 1})
    for e in db.scalars(visible_entries(db, user).order_by(KbEntry.updated_at.desc())):
        ids = [i for i in e.topic_ids or [] if i in tops]
        if not ids:
            continue
        hay = key_of(" ".join([e.text, e.original or "", TYPES[e.type], *(tops[i].name for i in ids),
                               *(a for i in ids for a in tops[i].aliases or [])]))
        if _match(hay, alts):
            hits.append({"url": f"/wissen/{ids[0]}#e{e.id}", "title": e.text,
                         "sub": TYPES[e.type] + " · " + ", ".join(tops[i].name for i in ids), "rank": 2})
    hits.sort(key=lambda h: h["rank"])
    return hits[:limit]


def synonyms_used(db: Session, q: str) -> list[str]:
    """Für die Trefferliste: welche Synonyme mitgesucht wurden."""
    toks = set(_tokens(q))
    out = []
    for g in synonym_groups(db):
        if toks & {key_of(w) for w in g.words}:
            out += [w for w in g.words if key_of(w) not in toks]
    return out


def record_miss(db: Session, user: User, q: str) -> None:
    q = " ".join(str(q or "").split())[:80]
    k = " ".join(_tokens(q))[:80]
    if not k:
        return
    row = db.scalar(select(KbSearchMiss).where(KbSearchMiss.key == k))
    if row:
        row.count, row.last_at, row.last_user, row.query = row.count + 1, utcnow(), user.id, q
    else:
        db.add(KbSearchMiss(key=k, query=q, last_user=user.id))


def misses(db: Session) -> list[KbSearchMiss]:
    return list(db.scalars(select(KbSearchMiss).order_by(KbSearchMiss.count.desc(), KbSearchMiss.last_at.desc()).limit(50)))
