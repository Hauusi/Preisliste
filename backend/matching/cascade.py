"""Matching-Kaskade alte -> neue Liste.

Reihenfolge: exakt -> normalisiert -> führende Nullen (pro Hersteller, F2) -> bestätigte
Zuordnungen -> unscharf (rapidfuzz). Automatisch übernommen werden nur die eindeutigen Treffer
der ersten vier Stufen. Unscharfe Treffer sind immer nur Vorschläge (F3) und müssen bestätigt werden.
Die KI-Stufe folgt in Gruppe C und liefert ebenfalls nur Vorschläge.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from rapidfuzz import fuzz, process

FUZZY_THRESHOLD = 70
FUZZY_CANDIDATES = 3


@dataclass(frozen=True)
class Item:
    id: int
    manufacturer_id: int | None
    number: str
    normalized: str
    description: str | None = None


@dataclass
class Candidate:
    old_id: int
    score: Decimal


@dataclass
class MatchResult:
    pairs: list[tuple[int, int, str, Decimal]] = field(default_factory=list)  # old, new, Methode, Score
    unclear: dict[int, list[Candidate]] = field(default_factory=dict)  # new_id -> Kandidaten
    unclear_reason: dict[int, str] = field(default_factory=dict)
    new_only: list[int] = field(default_factory=list)
    old_only: list[int] = field(default_factory=list)


def strip_zeros(normalized: str) -> str:
    return (normalized.lstrip("0") or "0") if normalized.isdigit() else normalized


def match(
    old: list[Item],
    new: list[Item],
    ignore_zeros: set[int | None] = frozenset(),
    decisions: dict[tuple[int | None, str, str], str] | None = None,
    threshold: int = FUZZY_THRESHOLD,
) -> MatchResult:
    decisions = decisions or {}
    res = MatchResult()
    old_left = {o.id: o for o in old}
    new_left = {n.id: n for n in new}

    def stage(method: str, key) -> None:
        olds, news = defaultdict(list), defaultdict(list)
        for o in old_left.values():
            k = key(o)
            if k is not None:
                olds[k].append(o)
        for n in new_left.values():
            k = key(n)
            if k is not None:
                news[k].append(n)
        for k, ns in news.items():
            os_ = olds.get(k)
            if not os_:
                continue
            if len(ns) == 1 and len(os_) == 1:
                res.pairs.append((os_[0].id, ns[0].id, method, Decimal(100)))
                del old_left[os_[0].id]
                del new_left[ns[0].id]
            else:
                # Mehrfach vorhandene Nummer: nicht automatisch zuordnen
                for n in ns:
                    res.unclear[n.id] = [Candidate(o.id, Decimal(100)) for o in os_]
                    res.unclear_reason[n.id] = (
                        f"Nummer mehrfach vorhanden (alt {len(os_)}x, neu {len(ns)}x), Stufe {method}"
                    )
                    del new_left[n.id]
                for o in os_:
                    old_left.pop(o.id, None)

    stage("EXAKT", lambda a: (a.manufacturer_id, a.number.strip()))
    stage("NORMALISIERT", lambda a: (a.manufacturer_id, a.normalized))
    stage("NULLEN", lambda a: (a.manufacturer_id, strip_zeros(a.normalized))
          if a.manufacturer_id in ignore_zeros else None)

    # Bestätigte Zuordnungen aus früheren Vergleichen
    confirmed = {(m, o, n) for (m, o, n), d in decisions.items() if d == "MATCH"}
    if confirmed:
        old_by_key = defaultdict(list)
        for o in old_left.values():
            old_by_key[(o.manufacturer_id, o.normalized)].append(o)
        for n in list(new_left.values()):
            hits = [o for (m, okey, nkey) in confirmed if m == n.manufacturer_id and nkey == n.normalized
                    for o in old_by_key.get((m, okey), []) if o.id in old_left]
            if len(hits) == 1:
                res.pairs.append((hits[0].id, n.id, "BESTAETIGT", Decimal(100)))
                del old_left[hits[0].id]
                del new_left[n.id]

    # Unscharf: nur Vorschläge
    old_by_mfr = defaultdict(list)
    for o in old_left.values():
        old_by_mfr[o.manufacturer_id].append(o)
    referenced: set[int] = set()
    for n in list(new_left.values()):
        pool = [o for o in old_by_mfr.get(n.manufacturer_id, [])
                if decisions.get((n.manufacturer_id, o.normalized, n.normalized)) != "NO_MATCH"]
        cands = fuzzy_candidates(n, pool, threshold)
        if cands:
            res.unclear[n.id] = cands
            res.unclear_reason[n.id] = "Unscharfer Treffer, bitte bestätigen"
            referenced.update(c.old_id for c in cands)
            del new_left[n.id]

    res.new_only = sorted(new_left)
    # Alte Artikel, die als Kandidat vorgeschlagen sind, gelten erst nach der Entscheidung als entfallen
    res.old_only = sorted(i for i in old_left if i not in referenced)
    return res


def fuzzy_candidates(n: Item, pool: list[Item], threshold: int) -> list[Candidate]:
    if not pool:
        return []
    by_number = process.extract(n.normalized, [o.normalized for o in pool], scorer=fuzz.ratio, limit=10)
    idx = {i for _, _, i in by_number}
    if n.description:
        descs = [o.description or "" for o in pool]
        by_desc = process.extract(n.description, descs, scorer=fuzz.token_set_ratio, limit=10)
        idx |= {i for _, _, i in by_desc}
    scored = []
    for i in idx:
        o = pool[i]
        num = fuzz.ratio(n.normalized, o.normalized)
        if n.description and o.description:
            score = 0.7 * num + 0.3 * fuzz.token_set_ratio(n.description, o.description)
        else:
            score = num
        if score >= threshold:
            scored.append(Candidate(o.id, Decimal(str(round(score, 1)))))
    scored.sort(key=lambda c: (-c.score, c.old_id))
    return scored[:FUZZY_CANDIDATES]
