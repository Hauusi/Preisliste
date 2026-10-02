"""Preisaktualisierung: neue Preisliste nur mit unseren Artikeln, Preise aus der Herstellerliste.

- Basis = unsere Vorjahresliste (welche Artikel wir führen), Quelle = neue Herstellerliste.
- Zuordnung über dieselbe Matching-Kaskade wie der Vergleich; unsichere Treffer werden nie übernommen.
- Gefunden: Herstellerpreis übernehmen und mit der Regel kalkulieren.
- Nicht gefunden: alten Preis behalten, als NICHT_IN_HERSTELLERLISTE markieren (ebenfalls kalkuliert).
- Artikel, die nur in der Herstellerliste stehen, werden ignoriert.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from backend.calculations.engine import PriceInput, RuleDefinition, calculate
from backend.comparison.service import match_articles, percent_change
from backend.models.entities import Article, PriceUpdate, PriceUpdateItem, RuleVersion

STATUSES = ("AKTUALISIERT", "UNVERAENDERT", "NICHT_IN_HERSTELLERLISTE", "NICHT_EINDEUTIG", "FEHLER")
STATUS_LABELS = {
    "AKTUALISIERT": "neuer Preis", "UNVERAENDERT": "Preis gleich", "NICHT_IN_HERSTELLERLISTE": "nicht in Herstellerliste",
    "NICHT_EINDEUTIG": "nicht eindeutig", "FEHLER": "Fehler",
}


def _price(a: Article | None, price_type: str):
    """Preis des Typs: ohne Staffel bevorzugt, sonst kleinste Staffel. (Betrag, Währung, Rabatt, Transport)"""
    if a is None:
        return None
    cands = [p for p in a.prices if p.price_type == price_type]
    if not cands:
        return None
    p = min(cands, key=lambda p: (p.min_quantity is not None, p.min_quantity or 0))
    return p


def run_update(db: Session, upd: PriceUpdate) -> dict:
    rule = RuleDefinition.model_validate(db.get(RuleVersion, upd.rule_version_id).definition) \
        if upd.rule_version_id else None

    def load(list_id):
        stmt = (select(Article).where(Article.price_list_id == list_id).options(selectinload(Article.prices)))
        return {a.id: a for a in db.scalars(stmt)}

    base, source = load(upd.base_price_list_id), load(upd.source_price_list_id)
    result = match_articles(db, base, source)
    pairs = {old: (new, method) for old, new, method, _ in result.pairs}
    unclear_old = defaultdict(list)
    for new_id, cands in result.unclear.items():
        for c in cands:
            unclear_old[c.old_id].append(source[new_id].article_number)

    rows, counts = [], defaultdict(int)
    for a in sorted(base.values(), key=lambda a: a.source_row):
        old_p = _price(a, upd.price_type)
        row = {"update_id": upd.id, "base_article_id": a.id, "manufacturer_id": a.manufacturer_id,
               "article_number": a.article_number, "description": a.description,
               "old_amount": old_p.amount if old_p else None, "currency": old_p.currency if old_p else None}
        new_id, method = pairs.get(a.id, (None, None))
        use_p = None
        if not a.article_number:
            row.update(status="FEHLER", note=f"Artikel ohne Artikelnummer (Zeile {a.source_row})")
        elif new_id is not None:
            new_p = _price(source[new_id], upd.price_type)
            row.update(source_article_id=new_id, match_method=method)
            if new_p is None:
                row.update(status="FEHLER", note=f"Kein {upd.price_type}-Preis in der Herstellerliste")
            elif old_p is not None and old_p.currency != new_p.currency:
                row.update(status="FEHLER", note=f"Währung abweichend ({old_p.currency} -> {new_p.currency})")
            else:
                use_p = new_p
                row.update(new_amount=new_p.amount, currency=new_p.currency)
                if old_p is not None:
                    row["difference"] = new_p.amount - old_p.amount
                    if old_p.amount != 0:
                        row["difference_percent"] = percent_change(old_p.amount, new_p.amount)
                    row["status"] = "UNVERAENDERT" if new_p.amount == old_p.amount else "AKTUALISIERT"
                else:
                    row["status"] = "AKTUALISIERT"
                    row["note"] = f"Kein alter {upd.price_type}-Preis"
        else:
            use_p = old_p
            if a.id in unclear_old:
                row.update(status="NICHT_EINDEUTIG",
                           note="Alter Preis behalten. Möglicher Treffer in der Herstellerliste: "
                                + ", ".join(unclear_old[a.id]) + " (im Vergleich bestätigen)")
            else:
                row.update(status="NICHT_IN_HERSTELLERLISTE", note="Alter Preis behalten")
            if old_p is None:
                row["status"] = "FEHLER"
                row["note"] = (row.get("note") or "") + f"; kein {upd.price_type}-Preis vorhanden"
        if rule is not None and use_p is not None and row["status"] != "FEHLER":
            calc = calculate(rule, [PriceInput(rule.start_price, use_p.amount, use_p.currency, None,
                                               use_p.discount_percent, use_p.transport_cost)], upd.quantity)
            row["trace"] = calc.trace
            if calc.status == "OK":
                row["calculated_amount"] = calc.result
            else:
                row["status"] = "FEHLER"
                row["note"] = f"Kalkulation: {calc.error}"
        counts[row["status"]] += 1
        rows.append(row)

    db.execute(delete(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id))
    if rows:
        db.execute(insert(PriceUpdateItem), rows)
    upd.summary = {"artikel": len(rows), **{s: counts.get(s, 0) for s in STATUSES},
                   "ignoriert_nur_beim_hersteller": len(result.new_only)}
    return upd.summary
