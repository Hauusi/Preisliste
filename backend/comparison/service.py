"""Vorjahresvergleich: Matching, Preisvergleich pro Staffel, Status, Zusammenfassung."""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from backend.calculations.engine import PriceInput, RuleDefinition, calculate
from backend.matching.cascade import Item, match
from backend.models.entities import (
    Article,
    Comparison,
    ComparisonItem,
    Manufacturer,
    MatchDecision,
    RuleVersion,
    utcnow,
)

STATUSES = (
    "UNVERAENDERT", "PREIS_ERHOEHT", "PREIS_GESENKT", "NEUER_ARTIKEL", "ENTFALLENER_ARTIKEL",
    "ARTIKEL_GEAENDERT", "NICHT_EINDEUTIG", "FEHLER",
)
STATUS_LABELS = {
    "UNVERAENDERT": "unverändert", "PREIS_ERHOEHT": "erhöht", "PREIS_GESENKT": "gesenkt",
    "NEUER_ARTIKEL": "neu", "ENTFALLENER_ARTIKEL": "entfallen", "ARTIKEL_GEAENDERT": "geändert",
    "NICHT_EINDEUTIG": "nicht eindeutig", "FEHLER": "Fehler",
}
COMPARE_TYPES = ("LISTE", "EK", "UVP", "KALKULIERT")
CHANGE_FIELDS = {"description": "Bezeichnung", "category": "Kategorie", "unit": "Einheit"}


def percent_change(old: Decimal, new: Decimal) -> Decimal:
    return ((new - old) / old * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _norm_text(v: str | None) -> str:
    return " ".join((v or "").split()).casefold()


def _changed(old: Article, new: Article) -> list[str]:
    return [label for f, label in CHANGE_FIELDS.items() if _norm_text(getattr(old, f)) != _norm_text(getattr(new, f))]


def _inputs(a: Article) -> list[PriceInput]:
    return [PriceInput(p.price_type, p.amount, p.currency, p.min_quantity, p.discount_percent, p.transport_cost)
            for p in a.prices]


def _amounts(a: Article, cmp: Comparison, rule: RuleDefinition | None) -> tuple[dict, str | None]:
    """{Mindestmenge: (Betrag, Währung)} oder Fehlertext."""
    if cmp.price_type == "KALKULIERT":
        res = calculate(rule, _inputs(a), cmp.quantity)
        if res.status != "OK":
            return {}, res.error
        return {None: (res.result, res.currency)}, None
    out = {}
    for p in a.prices:
        if p.price_type != cmp.price_type:
            continue
        if p.min_quantity in out:
            return {}, f"Mehrere {cmp.price_type}-Preise für dieselbe Staffel"
        out[p.min_quantity] = (p.amount, p.currency)
    if not out:
        return {}, f"Kein {cmp.price_type}-Preis"
    return out, None


def _base(a: Article) -> dict:
    return {"manufacturer_id": a.manufacturer_id, "article_number": a.article_number,
            "description": a.description, "category": a.category}


def _pair_items(cmp: Comparison, old: Article, new: Article, method: str, score, rule) -> list[dict]:
    changed = _changed(old, new)
    common = {**_base(new), "old_article_id": old.id, "new_article_id": new.id, "match_method": method,
              "confidence": score, "changed_fields": changed or None}
    old_am, old_err = _amounts(old, cmp, rule)
    new_am, new_err = _amounts(new, cmp, rule)
    if old_err or new_err:
        note = "; ".join(f"{side}: {e}" for side, e in (("alt", old_err), ("neu", new_err)) if e)
        return [{**common, "status": "FEHLER", "note": note}]
    items = []
    for qty in sorted(set(old_am) | set(new_am), key=lambda q: (q is not None, q or 0)):
        row = {**common, "min_quantity": qty}
        if qty not in old_am or qty not in new_am:
            side = "alten" if qty not in old_am else "neuen"
            label = f"ab {qty}" if qty is not None else "ohne Staffel"
            items.append({**row, "status": "NICHT_EINDEUTIG",
                          "old_amount": old_am.get(qty, (None,))[0], "new_amount": new_am.get(qty, (None,))[0],
                          "note": f"Staffel {label} fehlt in der {side} Liste"})
            continue
        (o, oc), (n, nc) = old_am[qty], new_am[qty]
        row.update(old_amount=o, new_amount=n, currency=nc)
        if oc != nc:
            items.append({**row, "status": "FEHLER", "note": f"Währung abweichend ({oc} -> {nc})"})
            continue
        row["difference"] = n - o
        if o == 0:
            items.append({**row, "status": "FEHLER", "note": "Alter Preis ist 0, Prozentänderung nicht berechenbar"})
            continue
        row["difference_percent"] = percent_change(o, n)
        if n > o:
            status = "PREIS_ERHOEHT"
        elif n < o:
            status = "PREIS_GESENKT"
        else:
            status = "ARTIKEL_GEAENDERT" if changed else "UNVERAENDERT"
        items.append({**row, "status": status})
    return items


def _single_amount(a: Article, cmp: Comparison, rule) -> tuple:
    am, err = _amounts(a, cmp, rule)
    if err or not am:
        return None, None
    key = min(am, key=lambda q: (q is not None, q or 0))
    return am[key]


def run_comparison(db: Session, cmp: Comparison) -> dict:
    rule = None
    if cmp.price_type == "KALKULIERT":
        rv = db.get(RuleVersion, cmp.rule_version_id)
        rule = RuleDefinition.model_validate(rv.definition)

    def load(list_id):
        stmt = select(Article).where(Article.price_list_id == list_id).options(selectinload(Article.prices))
        if cmp.manufacturer_id is not None:
            stmt = stmt.where(Article.manufacturer_id == cmp.manufacturer_id)
        return {a.id: a for a in db.scalars(stmt)}

    olds, news = load(cmp.old_price_list_id), load(cmp.new_price_list_id)
    to_item = lambda a: Item(a.id, a.manufacturer_id, a.article_number, a.article_number_normalized, a.description)
    ignore = {m.id for m in db.scalars(select(Manufacturer).where(Manufacturer.ignore_leading_zeros.is_(True)))}
    decisions = {(d.manufacturer_id, d.old_number_normalized, d.new_number_normalized): d.decision
                 for d in db.scalars(select(MatchDecision))}
    result = match([to_item(a) for a in olds.values() if a.article_number],
                   [to_item(a) for a in news.values() if a.article_number], ignore, decisions)

    rows: list[dict] = []
    for old_id, new_id, method, score in result.pairs:
        rows.extend(_pair_items(cmp, olds[old_id], news[new_id], method, score, rule))
    for new_id, cands in result.unclear.items():
        n = news[new_id]
        amount, cur = _single_amount(n, cmp, rule)
        reason = result.unclear_reason.get(new_id) or ""
        rows.append({**_base(n), "new_article_id": new_id, "status": "NICHT_EINDEUTIG", "new_amount": amount,
                     "currency": cur, "note": reason,
                     "match_method": "DOPPELT" if reason.startswith("Nummer mehrfach") else "UNSCHARF",
                     "candidates": [{"old_id": c.old_id, "score": str(c.score),
                                     "number": olds[c.old_id].article_number,
                                     "description": olds[c.old_id].description} for c in cands]})
    for new_id in result.new_only:
        n = news[new_id]
        amount, cur = _single_amount(n, cmp, rule)
        rows.append({**_base(n), "new_article_id": new_id, "status": "NEUER_ARTIKEL", "new_amount": amount,
                     "currency": cur})
    for old_id in result.old_only:
        o = olds[old_id]
        amount, cur = _single_amount(o, cmp, rule)
        rows.append({**_base(o), "old_article_id": old_id, "status": "ENTFALLENER_ARTIKEL", "old_amount": amount,
                     "currency": cur})
    # Artikel ohne Nummer (Importfehler) sichtbar machen statt verschweigen
    for side, arts in (("neu", news), ("alt", olds)):
        for a in arts.values():
            if not a.article_number:
                rows.append({**_base(a), f"{'new' if side == 'neu' else 'old'}_article_id": a.id,
                             "status": "FEHLER", "note": f"Artikel ohne Artikelnummer ({side}, Zeile {a.source_row})"})

    db.execute(delete(ComparisonItem).where(ComparisonItem.comparison_id == cmp.id))
    if rows:
        db.execute(insert(ComparisonItem), [{"comparison_id": cmp.id, **r} for r in rows])
    counts = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    cmp.summary = {"analysiert": len(rows), **{s: counts.get(s, 0) for s in STATUSES}}
    cmp.updated_at = utcnow()
    return cmp.summary


def decide(db: Session, cmp: Comparison, item: ComparisonItem, old_article_id: int | None, user_id: int) -> None:
    """Kandidat bestätigen (old_article_id) oder alle Kandidaten ablehnen (None). Danach neu berechnen."""
    if item.status != "NICHT_EINDEUTIG" or not item.candidates:
        raise ValueError("Für diesen Eintrag gibt es nichts zu entscheiden")
    if item.match_method == "DOPPELT":
        raise ValueError("Doppelte Artikelnummer: bitte in der Quelldatei bereinigen und neu importieren")
    new = db.get(Article, item.new_article_id)
    cand_ids = [c["old_id"] for c in (item.candidates or [])]
    if old_article_id is not None and old_article_id not in cand_ids:
        raise ValueError("Kandidat gehört nicht zu diesem Eintrag")
    for cid in cand_ids:
        old = db.get(Article, cid)
        decision = "MATCH" if cid == old_article_id else "NO_MATCH"
        key = dict(manufacturer_id=new.manufacturer_id, old_number_normalized=old.article_number_normalized,
                   new_number_normalized=new.article_number_normalized)
        existing = db.scalar(select(MatchDecision).filter_by(**key))
        if existing:
            existing.decision, existing.decided_by, existing.decided_at = decision, user_id, utcnow()
        else:
            db.add(MatchDecision(**key, decision=decision, decided_by=user_id))
    db.flush()
    run_comparison(db, cmp)
