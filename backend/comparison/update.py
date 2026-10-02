"""Jahresabgleich: unsere EK/VK-Liste (Vorjahr) + neue Herstellerliste -> neue EK/VK-Liste.

Ablauf pro Artikel unserer Liste:
- Zuordnung zur Herstellerliste über die Matching-Kaskade (unsichere Treffer werden nie übernommen).
- EK neu = Preis der Herstellerliste (Hersteller liefert EK) bzw. UVP - Händlerrabatt (Hersteller liefert UVP).
- VK neu = Regel des Herstellers, angewendet auf EK neu.
- Auffälligkeiten (Prüfgründe) verlangen eine Bestätigung, bevor final exportiert werden kann.
Artikel, die nur in der Herstellerliste stehen, werden ignoriert.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from backend.calculations.engine import PriceInput, RuleDefinition, calculate
from backend.comparison.service import match_articles, percent_change
from backend.models.entities import (
    Article,
    Manufacturer,
    MatchDecision,
    PriceUpdate,
    PriceUpdateItem,
    RuleVersion,
    utcnow,
)

CENT = Decimal("0.01")
STATUSES = ("OK", "PRUEFEN", "NICHT_EINDEUTIG", "NICHT_IN_HERSTELLERLISTE", "FEHLER")
STATUS_LABELS = {
    "OK": "in Ordnung", "PRUEFEN": "prüfen", "NICHT_EINDEUTIG": "Zuordnung unklar",
    "NICHT_IN_HERSTELLERLISTE": "fehlt beim Hersteller", "FEHLER": "Fehler",
}
REASON_LABELS = {
    "EK_AENDERUNG": "EK-Änderung über Prüfschwelle",
    "VK_UNTER_EK": "VK neu liegt unter EK neu",
    "PREIS_NULL": "Preis ist 0",
    "KEIN_ALTER_EK": "kein EK im Vorjahr",
    "KEIN_ALTER_VK": "kein VK im Vorjahr",
    "UNKLAR": "Zuordnung unklar",
    "FEHLT": "fehlt in der Herstellerliste",
    "FEHLER": "Berechnung nicht möglich",
}


def _price(a: Article | None, price_type: str):
    """Preis des Typs: ohne Staffel bevorzugt, sonst kleinste Staffel."""
    if a is None:
        return None
    cands = [p for p in a.prices if p.price_type == price_type]
    if not cands:
        return None
    return min(cands, key=lambda p: (p.min_quantity is not None, p.min_quantity or 0))


def _pct(old, new):
    return percent_change(old, new) if old not in (None, Decimal(0)) and new is not None else None


class _Ctx:
    def __init__(self, db: Session, upd: PriceUpdate):
        self.upd = upd
        rv = db.get(RuleVersion, upd.rule_version_id) if upd.rule_version_id else None
        self.rule = RuleDefinition.model_validate(rv.definition) if rv else None
        self.basis = upd.price_type  # EK oder UVP: was die Herstellerliste liefert
        self.discount = upd.dealer_discount
        self.threshold = upd.review_threshold if upd.review_threshold is not None else Decimal(10)


def compute_item(ctx: _Ctx, base: Article, source: Article | None, method: str | None,
                 candidates: list[dict] | None = None) -> dict:
    """Werte und Prüfgründe für einen Artikel unserer Liste berechnen."""
    ek_old_p, vk_old_p = _price(base, "EK"), _price(base, "LISTE")
    ek_old = ek_old_p.amount if ek_old_p else None
    vk_old = vk_old_p.amount if vk_old_p else None
    currency = (ek_old_p or vk_old_p).currency if (ek_old_p or vk_old_p) else None
    row = {"base_article_id": base.id, "manufacturer_id": base.manufacturer_id,
           "article_number": base.article_number, "description": base.description,
           "old_amount": ek_old, "vk_old": vk_old, "currency": currency, "source_article_id": None,
           "match_method": method, "source_amount": None, "new_amount": None, "calculated_amount": None,
           "difference": None, "difference_percent": None, "vk_difference": None, "vk_difference_percent": None,
           "trace": None, "candidates": candidates or None, "note": None}
    reasons: list[str] = []
    notes: list[str] = []

    def keep_old(status: str, reason: str, note: str):
        reasons.append(reason)
        notes.append(note)
        row.update(status=status, final_ek=ek_old, final_vk=vk_old, decision="ALT")

    if not base.article_number:
        keep_old("FEHLER", "FEHLER", f"Artikel ohne Artikelnummer (Zeile {base.source_row})")
    elif candidates:
        keep_old("NICHT_EINDEUTIG", "UNKLAR", "Möglicher Treffer in der Herstellerliste, bitte auswählen")
    elif source is None:
        keep_old("NICHT_IN_HERSTELLERLISTE", "FEHLT", "Fehlt in der Herstellerliste – alter EK und VK bleiben")
    else:
        row["source_article_id"] = source.id
        src = _price(source, ctx.basis)
        if src is None:
            keep_old("FEHLER", "FEHLER", f"Herstellerliste enthält keinen {ctx.basis}-Preis für diesen Artikel")
        elif currency and src.currency != currency:
            keep_old("FEHLER", "FEHLER", f"Währung abweichend ({currency} -> {src.currency})")
        else:
            row["source_amount"] = src.amount
            currency = row["currency"] = src.currency
            if ctx.basis == "UVP":
                if ctx.discount is None:
                    keep_old("FEHLER", "FEHLER", "Händlerrabatt beim Hersteller nicht hinterlegt")
                    ek_new = None
                else:
                    ek_new = (src.amount * (Decimal(100) - ctx.discount) / Decimal(100)).quantize(
                        CENT, rounding=ROUND_HALF_UP)
            else:
                ek_new = src.amount
            if ek_new is not None:
                row["new_amount"] = ek_new
                vk_new = None
                if ctx.rule is None:
                    keep_old("FEHLER", "FEHLER", "Keine Kalkulationsregel gewählt")
                else:
                    calc = calculate(ctx.rule, [PriceInput(ctx.rule.start_price, ek_new, currency, None,
                                                           src.discount_percent, src.transport_cost)],
                                     ctx.upd.quantity)
                    row["trace"] = calc.trace
                    if calc.status != "OK":
                        keep_old("FEHLER", "FEHLER", f"Kalkulation: {calc.error}")
                    else:
                        vk_new = calc.result
                if vk_new is not None:
                    row.update(calculated_amount=vk_new, final_ek=ek_new, final_vk=vk_new, decision="NEU")
                    if ek_old is not None:
                        row["difference"] = ek_new - ek_old
                        row["difference_percent"] = _pct(ek_old, ek_new)
                    if vk_old is not None:
                        row["vk_difference"] = vk_new - vk_old
                        row["vk_difference_percent"] = _pct(vk_old, vk_new)
                    pct = row["difference_percent"]
                    if pct is not None and abs(pct) >= ctx.threshold:
                        reasons.append("EK_AENDERUNG")
                        notes.append(f"EK {'+' if pct > 0 else ''}{pct} % (Prüfschwelle {ctx.threshold} %)")
                    if ek_old == 0 and ek_new != 0:
                        reasons.append("EK_AENDERUNG")
                    if vk_new < ek_new:
                        reasons.append("VK_UNTER_EK")
                    if ek_new == 0 or vk_new == 0:
                        reasons.append("PREIS_NULL")
                    if ek_old is None:
                        reasons.append("KEIN_ALTER_EK")
                    if vk_old is None:
                        reasons.append("KEIN_ALTER_VK")
                    row["status"] = "PRUEFEN" if reasons else "OK"
    row["reasons"] = sorted(set(reasons)) or None
    row["note"] = "; ".join(notes) or None
    row["needs_review"] = row["status"] != "OK"
    return row


def run_update(db: Session, upd: PriceUpdate) -> dict:
    ctx = _Ctx(db, upd)

    def load(list_id):
        stmt = select(Article).where(Article.price_list_id == list_id).options(selectinload(Article.prices))
        return {a.id: a for a in db.scalars(stmt)}

    base, source = load(upd.base_price_list_id), load(upd.source_price_list_id)
    result = match_articles(db, base, source)
    pairs = {old: (new, method) for old, new, method, _ in result.pairs}
    cand_for_old = defaultdict(list)
    for new_id, cands in result.unclear.items():
        reason = result.unclear_reason.get(new_id, "")
        if reason.startswith("Nummer mehrfach"):
            continue  # Dubletten können nicht per Klick aufgelöst werden -> unten als FEHLER
        for c in cands:
            n = source[new_id]
            cand_for_old[c.old_id].append({"new_id": n.id, "number": n.article_number,
                                           "description": n.description, "score": str(c.score)})
    duplicate_old = {c.old_id for nid, cs in result.unclear.items()
                     if result.unclear_reason.get(nid, "").startswith("Nummer mehrfach") for c in cs}

    rows = []
    for a in sorted(base.values(), key=lambda a: a.source_row):
        new_id, method = pairs.get(a.id, (None, None))
        row = compute_item(ctx, a, source.get(new_id) if new_id else None, method, cand_for_old.get(a.id))
        if a.id in duplicate_old:
            row.update(status="FEHLER", reasons=["FEHLER"], needs_review=True, decision="ALT",
                       final_ek=row["old_amount"], final_vk=row["vk_old"],
                       note="Artikelnummer kommt in einer Liste mehrfach vor – bitte in der Excel-Datei bereinigen")
        rows.append({"update_id": upd.id, **row})
    db.execute(delete(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id))
    if rows:
        db.execute(insert(PriceUpdateItem), rows)
    upd.summary = summarize(rows, len(result.new_only))
    return upd.summary


def summarize(rows: list, ignored: int) -> dict:
    counts = defaultdict(int)
    open_ = 0
    for r in rows:
        status = r["status"] if isinstance(r, dict) else r.status
        counts[status] += 1
        needs = r["needs_review"] if isinstance(r, dict) else r.needs_review
        reviewed = r.get("reviewed_at") if isinstance(r, dict) else r.reviewed_at
        if needs and not reviewed:
            open_ += 1
    return {"artikel": len(rows), **{s: counts.get(s, 0) for s in STATUSES}, "offen": open_,
            "ignoriert_nur_beim_hersteller": ignored}


def refresh_summary(db: Session, upd: PriceUpdate) -> None:
    items = db.scalars(select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id)).all()
    upd.summary = summarize(items, (upd.summary or {}).get("ignoriert_nur_beim_hersteller", 0))


# ---------- Prüfaktionen ----------

def accept(db: Session, item: PriceUpdateItem, user_id: int, manual_vk: Decimal | None = None) -> None:
    """Position als geprüft bestätigen. Optional VK von Hand setzen."""
    if manual_vk is not None:
        if manual_vk < 0:
            raise ValueError("VK darf nicht negativ sein")
        if item.status == "FEHLER":
            raise ValueError("Bei Fehlern bleibt der alte Preis")
        ek = item.final_ek
        vk = manual_vk.quantize(CENT, rounding=ROUND_HALF_UP)
        if ek is not None and vk < ek:
            raise ValueError(f"VK {vk} liegt unter dem EK {ek}")
        item.final_vk, item.decision = vk, "MANUELL"
    item.reviewed_by, item.reviewed_at = user_id, utcnow()


def choose_candidate(db: Session, upd: PriceUpdate, item: PriceUpdateItem, new_id: int | None, user_id: int) -> None:
    """Unklare Zuordnung auflösen: Kandidat übernehmen oder 'kein Treffer'. Entscheidung wird gespeichert."""
    if item.status != "NICHT_EINDEUTIG" or not item.candidates:
        raise ValueError("Für diese Position gibt es nichts zuzuordnen")
    ids = [c["new_id"] for c in item.candidates]
    if new_id is not None and new_id not in ids:
        raise ValueError("Kandidat gehört nicht zu dieser Position")
    if new_id is not None and db.scalar(select(PriceUpdateItem.id).where(
            PriceUpdateItem.update_id == upd.id, PriceUpdateItem.source_article_id == new_id,
            PriceUpdateItem.id != item.id)):
        raise ValueError("Dieser Herstellerartikel ist bereits einem anderen Artikel zugeordnet")
    base = db.get(Article, item.base_article_id)
    for cid in ids:
        cand = db.get(Article, cid)
        key = dict(manufacturer_id=base.manufacturer_id, old_number_normalized=base.article_number_normalized,
                   new_number_normalized=cand.article_number_normalized)
        decision = "MATCH" if cid == new_id else "NO_MATCH"
        existing = db.scalar(select(MatchDecision).filter_by(**key))
        if existing:
            existing.decision, existing.decided_by, existing.decided_at = decision, user_id, utcnow()
        else:
            db.add(MatchDecision(**key, decision=decision, decided_by=user_id))
    ctx = _Ctx(db, upd)
    source = db.get(Article, new_id) if new_id else None
    row = compute_item(ctx, base, source, "BESTAETIGT" if source else None)
    for k, v in row.items():
        setattr(item, k, v)
    item.reviewed_by = item.reviewed_at = None
    if item.needs_review and source is None:
        # 'kein Treffer' ist selbst die Prüfentscheidung: alter EK/VK bleibt
        item.reviewed_by, item.reviewed_at = user_id, utcnow()


def bulk_accept(db: Session, upd: PriceUpdate, user_id: int, status: str | None, reason: str | None) -> int:
    """Alle offenen Positionen eines Filters bestätigen (ohne manuelle Änderungen). Unklare Zuordnungen nie."""
    stmt = select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id,
                                         PriceUpdateItem.needs_review.is_(True),
                                         PriceUpdateItem.reviewed_at.is_(None),
                                         PriceUpdateItem.status != "NICHT_EINDEUTIG")
    if status:
        stmt = stmt.where(PriceUpdateItem.status == status)
    n = 0
    for item in db.scalars(stmt):
        if reason and reason not in (item.reasons or []):
            continue
        accept(db, item, user_id)
        n += 1
    return n


def manufacturer_settings(m: Manufacturer | None) -> dict:
    return {"basis": (m.list_basis if m else "EK") or "EK", "discount": m.dealer_discount if m else None,
            "threshold": m.review_threshold if m and m.review_threshold is not None else Decimal(10)}
