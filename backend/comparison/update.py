"""Jahresabgleich: unsere aktuelle EK/VK-Liste + neue Herstellerliste -> neue EK/VK-Liste.

Ablauf pro Artikel unserer Liste:
- Zuordnung zur Herstellerliste über die Matching-Kaskade (unsichere Treffer werden nie übernommen).
- EK neu = Preis der Herstellerliste (EK) bzw. UVP - Händlerrabatt, bei Fremdwährung × Umrechnungskurs.
- VK neu = Regel des Herstellers (oder Ausnahme-Regel der Serie), angewendet auf EK neu.
- Jeder VK wird unabhängig nachgerechnet (Gegenrechnung). Abweichung = FEHLER, alter Preis bleibt.
- Auffälligkeiten (Prüfgründe) verlangen eine Bestätigung, bevor final exportiert werden kann.
Artikel, die nur in der Herstellerliste stehen, werden ignoriert.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from backend.calculations.engine import PriceInput, RuleDefinition, calculate
from backend.calculations.verify import recalc
from backend.comparison.service import match_articles, percent_change
from backend.excel.importer import normalize_article_number
from backend.models.entities import (
    Article,
    ArticlePrice,
    ImportMessage,
    Manufacturer,
    MatchDecision,
    PriceList,
    PriceUpdate,
    PriceUpdateItem,
    Rule,
    RuleException,
    RuleVersion,
    utcnow,
)

CENT = Decimal("0.01")
STATUSES = ("OK", "PRUEFEN", "NICHT_EINDEUTIG", "NICHT_IN_HERSTELLERLISTE", "UNVERAENDERT", "FEHLER")
STATUS_LABELS = {
    "OK": "in Ordnung", "PRUEFEN": "prüfen", "NICHT_EINDEUTIG": "Zuordnung unklar",
    "NICHT_IN_HERSTELLERLISTE": "fehlt beim Hersteller", "UNVERAENDERT": "nicht in Teilliste (unverändert)",
    "FEHLER": "Fehler",
}
REASON_LABELS = {
    "EK_AENDERUNG": "EK-Änderung über Prüfschwelle",
    "VK_ABWEICHUNG": "VK-Änderung passt nicht zur EK-Änderung (Vorjahr anders kalkuliert?)",
    "VK_UNTER_EK": "VK neu liegt unter EK neu",
    "PREIS_NULL": "Preis ist 0",
    "KEIN_ALTER_EK": "kein EK im Vorjahr",
    "KEIN_ALTER_VK": "kein VK im Vorjahr",
    "NICHT_GEGENGEPRUEFT": "Kalkulation nicht automatisch nachrechenbar",
    "UNKLAR": "Zuordnung unklar",
    "FEHLT": "fehlt in der Herstellerliste",
    "FEHLER": "Berechnung nicht möglich",
}
SCOPES = {"VOLL": "Jahrespreisliste (vollständig)", "TEIL": "Preiserhöhung einzelner Serien (Teilliste)"}


def de(v: Decimal | None, min_places: int = 2) -> str:
    """Decimal deutsch für Rechenwege: 1234.5 -> 1.234,50, 0.095 -> 0,095."""
    if v is None:
        return ""
    places = max(min_places, -v.normalize().as_tuple().exponent)
    text = f"{abs(v):,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + text


def normalize_series(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


EXCEPTION_LABELS = {"ARTIKEL": "Artikel", "PREFIX": "Nummer beginnt mit", "SERIE": "Serie"}


def normalize_exception(match_type: str, value: str) -> str:
    return normalize_article_number(value) if match_type in ("PREFIX", "ARTIKEL") else normalize_series(value)


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


def snapshot_exceptions(db: Session, manufacturer_id: int | None) -> list[dict]:
    """Aktuelle Serien-Ausnahmen eines Herstellers mit der jeweils aktuellen Regelversion festhalten."""
    if manufacturer_id is None:
        return []
    out = []
    for ex in db.scalars(select(RuleException).where(RuleException.manufacturer_id == manufacturer_id)
                         .order_by(RuleException.id)):
        rule = db.get(Rule, ex.rule_id)
        if rule is None or rule.deleted:
            continue
        rv = db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id,
                                                 RuleVersion.version == rule.current_version))
        out.append({"id": ex.id, "typ": ex.match_type, "wert": ex.value, "norm": ex.value_normalized,
                    "rule_version_id": rv.id, "regel": f"{rule.name} v{rv.version}"})
    return out


class _Ctx:
    def __init__(self, db: Session, upd: PriceUpdate):
        self.upd = upd
        rv = db.get(RuleVersion, upd.rule_version_id) if upd.rule_version_id else None
        self.rule = RuleDefinition.model_validate(rv.definition) if rv else None
        self.rule_label = f"Standard: {db.get(Rule, rv.rule_id).name} v{rv.version}" if rv else None
        self.basis = upd.price_type  # EK oder UVP: was die Herstellerliste liefert
        self.discount = upd.dealer_discount
        self.threshold = upd.review_threshold if upd.review_threshold is not None else Decimal(10)
        self.list_currency = upd.list_currency
        self.rate = upd.exchange_rate
        # Artikel, die der Hersteller als entfallen kennzeichnet (Importmeldung ENTFALLEN)
        rows = dict(db.execute(select(ImportMessage.source_row, ImportMessage.text).where(
            ImportMessage.price_list_id == upd.source_price_list_id, ImportMessage.code == "ENTFALLEN")).all())
        self.discontinued = {a_id: rows[r] for a_id, r in db.execute(select(Article.id, Article.source_row).where(
            Article.price_list_id == upd.source_price_list_id, Article.source_row.in_(list(rows)))).all()} if rows else {}
        self.exceptions = []
        for ex in upd.exceptions or []:
            erv = db.get(RuleVersion, ex["rule_version_id"])
            typ = EXCEPTION_LABELS.get(ex["typ"], ex["typ"])
            self.exceptions.append({**ex, "rule": RuleDefinition.model_validate(erv.definition),
                                    "label": f"Ausnahme {typ} „{ex['wert']}“: {ex['regel']}"})

    def pick_rule(self, base: Article, source: Article | None):
        """(Regel, Bezeichnung, Fehler). Mehrere passende Ausnahmen mit verschiedenen Regeln = Fehler."""
        series = {normalize_series(base.category), normalize_series(source.category if source else None)} - {""}
        number = base.article_number_normalized or ""
        # Einzelne Artikel (von Hand ausgewählt) gehen vor Nummernanfang/Serie
        hits = [ex for ex in self.exceptions if ex["typ"] == "ARTIKEL" and ex["norm"] == number]
        if not hits:
            hits = [ex for ex in self.exceptions
                    if (ex["typ"] == "SERIE" and ex["norm"] in series)
                    or (ex["typ"] == "PREFIX" and number.startswith(ex["norm"]))]
        if len({ex["rule_version_id"] for ex in hits}) > 1:
            return None, None, "Mehrere Ausnahmen passen: " + "; ".join(ex["label"] for ex in hits)
        if hits:
            return hits[0]["rule"], hits[0]["label"], None
        return self.rule, self.rule_label, None


def compute_item(ctx: _Ctx, base: Article, source: Article | None, method: str | None,
                 candidates: list[dict] | None = None) -> dict:
    """Werte und Prüfgründe für einen Artikel unserer Liste berechnen."""
    ek_old_p, vk_old_p = _price(base, "EK"), _price(base, "LISTE")
    ek_old = ek_old_p.amount if ek_old_p else None
    vk_old = vk_old_p.amount if vk_old_p else None
    currency = (ek_old_p or vk_old_p).currency if (ek_old_p or vk_old_p) else "EUR"
    row = {"base_article_id": base.id, "manufacturer_id": base.manufacturer_id,
           "article_number": base.article_number, "description": base.description,
           "old_amount": ek_old, "vk_old": vk_old, "currency": currency, "source_article_id": None,
           "match_method": method, "source_amount": None, "source_currency": None, "new_amount": None,
           "calculated_amount": None, "difference": None, "difference_percent": None, "vk_difference": None,
           "vk_difference_percent": None, "trace": None, "candidates": candidates or None, "note": None,
           "ek_text": None, "rule_label": None, "factor": None, "check_ok": None}
    reasons: list[str] = []
    notes: list[str] = []

    def keep_old(status: str, reason: str | None, note: str):
        if reason:
            reasons.append(reason)
        notes.append(note)
        row.update(status=status, final_ek=ek_old, final_vk=vk_old, decision="ALT")

    if not base.article_number:
        keep_old("FEHLER", "FEHLER", f"Artikel ohne Artikelnummer (Zeile {base.source_row})")
    elif candidates:
        keep_old("NICHT_EINDEUTIG", "UNKLAR", "Möglicher Treffer in der Herstellerliste, bitte auswählen")
    elif source is None and ctx.upd.scope == "TEIL":
        keep_old("UNVERAENDERT", None, "Nicht in der Teilliste – EK und VK bleiben unverändert")
    elif source is None:
        keep_old("NICHT_IN_HERSTELLERLISTE", "FEHLT", "Fehlt in der Herstellerliste – alter EK und VK bleiben")
    else:
        row["source_article_id"] = source.id
        _compute_prices(ctx, base, source, row, reasons, notes, keep_old, ek_old, vk_old, currency)
    row["reasons"] = sorted(set(reasons)) or None
    row["note"] = "; ".join(notes) or None
    row["needs_review"] = row["status"] not in ("OK", "UNVERAENDERT")
    return row


def _compute_prices(ctx, base, source, row, reasons, notes, keep_old, ek_old, vk_old, currency):
    src = _price(source, ctx.basis)
    if src is None and source.id in ctx.discontinued:
        row["source_article_id"] = None
        return keep_old("NICHT_IN_HERSTELLERLISTE", "FEHLT", f"{ctx.discontinued[source.id]} – alter EK und VK bleiben")
    if src is None:
        return keep_old("FEHLER", "FEHLER", f"Herstellerliste enthält keinen {ctx.basis}-Preis für diesen Artikel")
    row.update(source_amount=src.amount, source_currency=src.currency)
    label = "UVP" if ctx.basis == "UVP" else "EK"
    text = f"{label} Hersteller {de(src.amount)} {src.currency}"
    value, changed = src.amount, False
    if ctx.basis == "UVP":
        if ctx.discount is None:
            return keep_old("FEHLER", "FEHLER", "Händlerrabatt beim Hersteller nicht hinterlegt")
        value = value * (Decimal(100) - ctx.discount) / Decimal(100)
        text += f" − {de(ctx.discount, 0)} % Händlerrabatt"
        changed = True
    if src.currency != currency:
        if not (ctx.rate and src.currency == ctx.list_currency and currency == "EUR"):
            return keep_old("FEHLER", "FEHLER",
                            f"Herstellerpreis in {src.currency}, unsere Liste in {currency}: "
                            f"kein Umrechnungskurs {src.currency} → {currency} beim Hersteller hinterlegt")
        value = value * ctx.rate
        text += f" × Kurs {de(ctx.rate, 0)}"
        changed = True
    ek_new = value.quantize(CENT, rounding=ROUND_HALF_UP) if changed else value
    if changed:
        text += f" = {de(ek_new)} {currency}"
    row.update(new_amount=ek_new, ek_text=text)

    rule, rule_label, rule_error = ctx.pick_rule(base, source)
    row["rule_label"] = rule_label
    if rule_error:
        return keep_old("FEHLER", "FEHLER", rule_error)
    if rule is None:
        return keep_old("FEHLER", "FEHLER", "Keine Kalkulationsregel gewählt")
    calc = calculate(rule, [PriceInput(rule.start_price, ek_new, currency, None, src.discount_percent,
                                       src.transport_cost)], ctx.upd.quantity)
    row["trace"] = calc.trace
    if calc.status != "OK":
        return keep_old("FEHLER", "FEHLER", f"Kalkulation: {calc.error}")
    vk_new = calc.result
    check, why = recalc(rule, ek_new)
    if check is not None and check != vk_new:
        row["check_ok"] = False
        return keep_old("FEHLER", "FEHLER", f"Gegenrechnung abweichend: Regel {de(vk_new)}, "
                                            f"Gegenrechnung {de(check)} – bitte melden")
    row["check_ok"] = True if check is not None else None  # None = nicht nachrechenbar (nicht: Abweichung)
    if check is None:
        reasons.append("NICHT_GEGENGEPRUEFT")
        notes.append(why)
    row.update(calculated_amount=vk_new, final_ek=ek_new, final_vk=vk_new, decision="NEU")
    if ek_new > 0:
        row["factor"] = (vk_new / ek_new).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if ek_old is not None:
        row["difference"] = ek_new - ek_old
        row["difference_percent"] = _pct(ek_old, ek_new)
    if vk_old is not None:
        row["vk_difference"] = vk_new - vk_old
        row["vk_difference_percent"] = _pct(vk_old, vk_new)
    pct, vk_pct = row["difference_percent"], row["vk_difference_percent"]
    if pct is not None and abs(pct) >= ctx.threshold:
        reasons.append("EK_AENDERUNG")
        notes.append(f"EK {'+' if pct > 0 else ''}{de(pct)} % (Prüfschwelle {de(ctx.threshold, 0)} %)")
    if ek_old == 0 and ek_new != 0:
        reasons.append("EK_AENDERUNG")
    if pct is not None and vk_pct is not None and abs(vk_pct - pct) >= ctx.threshold:
        reasons.append("VK_ABWEICHUNG")
        notes.append(f"EK {de(pct)} %, VK {de(vk_pct)} %")
    if vk_new < ek_new:
        reasons.append("VK_UNTER_EK")
    if ek_new == 0 or vk_new == 0:
        reasons.append("PREIS_NULL")
    if ek_old is None:
        reasons.append("KEIN_ALTER_EK")
    if vk_old is None:
        reasons.append("KEIN_ALTER_VK")
    row["status"] = "PRUEFEN" if reasons else "OK"


def _drop_identical_duplicates(source: dict, basis: str) -> dict:
    """Doppelte Zeilen der Herstellerliste mit identischem Preis zählen einmal (kommt in echten Listen oft vor).
    Doppelte Nummern mit unterschiedlichem Preis bleiben doppelt und werden als Fehler gemeldet."""
    groups = defaultdict(list)
    for a in source.values():
        if a.article_number_normalized:
            groups[(a.manufacturer_id, a.article_number_normalized)].append(a)
    drop = set()
    for arts in groups.values():
        if len(arts) > 1:
            prices = {(p.amount, p.currency) for a in arts for p in [_price(a, basis)] if p is not None}
            if len(prices) == 1 and all(_price(a, basis) is not None for a in arts):
                drop |= {a.id for a in sorted(arts, key=lambda a: a.source_row)[1:]}
    return {k: v for k, v in source.items() if k not in drop}


def run_update(db: Session, upd: PriceUpdate) -> dict:
    ctx = _Ctx(db, upd)

    def load(list_id):
        stmt = select(Article).where(Article.price_list_id == list_id).options(selectinload(Article.prices))
        return {a.id: a for a in db.scalars(stmt)}

    base, source = load(upd.base_price_list_id), load(upd.source_price_list_id)
    source = _drop_identical_duplicates(source, ctx.basis)
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
        _decide(db, base, db.get(Article, cid), "MATCH" if cid == new_id else "NO_MATCH", user_id)
    ctx = _Ctx(db, upd)
    source = db.get(Article, new_id) if new_id else None
    row = compute_item(ctx, base, source, "BESTAETIGT" if source else None)
    for k, v in row.items():
        setattr(item, k, v)
    item.reviewed_by = item.reviewed_at = None
    if item.needs_review and source is None:
        # 'kein Treffer' ist selbst die Prüfentscheidung: alter EK/VK bleibt
        item.reviewed_by, item.reviewed_at = user_id, utcnow()


def _decide(db: Session, base: Article, cand: Article, decision: str, user_id: int) -> None:
    """Zuordnungsentscheidung speichern; gilt auch in künftigen Abgleichen und Vergleichen."""
    key = dict(manufacturer_id=base.manufacturer_id, old_number_normalized=base.article_number_normalized,
               new_number_normalized=cand.article_number_normalized)
    existing = db.scalar(select(MatchDecision).filter_by(**key))
    if existing:
        existing.decision, existing.decided_by, existing.decided_at = decision, user_id, utcnow()
    else:
        db.add(MatchDecision(**key, decision=decision, decided_by=user_id))


def decide_ai_hint(db: Session, upd: PriceUpdate, item: PriceUpdateItem, accept_it: bool, user_id: int) -> None:
    """KI-Einschätzung übernehmen (Artikel neu berechnen) oder ablehnen. Nie automatisch."""
    hint = item.ai_hint or {}
    if item.reviewed_at or item.status not in ("NICHT_IN_HERSTELLERLISTE", "NICHT_EINDEUTIG"):
        raise ValueError("Für diese Position gibt es keine offene KI-Einschätzung")
    if hint.get("status") != "TREFFER" or not hint.get("new_id"):
        raise ValueError("Die KI hat hier keinen Treffer vorgeschlagen")
    base = db.get(Article, item.base_article_id)
    cand = db.get(Article, hint["new_id"])
    if cand is None or cand.price_list_id != upd.source_price_list_id:
        raise ValueError("Vorgeschlagener Artikel gehört nicht zur Herstellerliste")
    if not accept_it:
        _decide(db, base, cand, "NO_MATCH", user_id)
        item.ai_hint = {**hint, "status": "ABGELEHNT"}
        return
    if db.scalar(select(PriceUpdateItem.id).where(PriceUpdateItem.update_id == upd.id,
                                                  PriceUpdateItem.source_article_id == cand.id,
                                                  PriceUpdateItem.id != item.id)):
        raise ValueError("Dieser Herstellerartikel ist bereits einem anderen Artikel zugeordnet")
    _decide(db, base, cand, "MATCH", user_id)
    row = compute_item(_Ctx(db, upd), base, cand, "BESTAETIGT")
    for k, v in row.items():
        setattr(item, k, v)
    item.ai_hint = {**hint, "status": "UEBERNOMMEN"}
    item.reviewed_by = item.reviewed_at = None


def bulk_accept(db: Session, upd: PriceUpdate, user_id: int, status: str | None, reason: str | None) -> int:
    """Alle offenen Positionen eines Filters bestätigen (ohne manuelle Änderungen).
    Unklare Zuordnungen und Fehler nie: die müssen einzeln entschieden werden."""
    stmt = select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id,
                                         PriceUpdateItem.needs_review.is_(True),
                                         PriceUpdateItem.reviewed_at.is_(None),
                                         PriceUpdateItem.status.not_in(("NICHT_EINDEUTIG", "FEHLER")))
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
            "threshold": m.review_threshold if m and m.review_threshold is not None else Decimal(10),
            "currency": (m.list_currency if m else "EUR") or "EUR", "rate": m.exchange_rate if m else None}


def adopt_as_current(db: Session, upd: PriceUpdate, user_id: int) -> PriceList:
    """Geprüftes Ergebnis als neue aktuelle Liste (unsere EK/VK-Liste) speichern."""
    if upd.adopted_list_id:
        raise ValueError("Dieser Abgleich wurde bereits als aktuelle Liste übernommen")
    refresh_summary(db, upd)
    if upd.summary.get("offen"):
        raise ValueError(f"Noch {upd.summary['offen']} Positionen ungeprüft")
    base = upd.base_list
    stem = base.name.split(" – Stand ")[0]
    pl = PriceList(name=f"{stem} – Stand {utcnow():%d.%m.%Y}"[:255], source_file=f"Jahresabgleich #{upd.id}",
                   stored_file=base.stored_file, file_sha256=base.file_sha256, manufacturer_id=base.manufacturer_id,
                   currency=base.currency, status="IMPORTIERT", kind="UNSERE", uploaded_by=user_id,
                   valid_from=upd.valid_from,
                   imported_at=utcnow(),
                   summary={"aus_abgleich": upd.id, "basis_liste": base.id, "herstellerliste": upd.source_price_list_id,
                            "articles": 0, "messages": {}})
    db.add(pl)
    db.flush()
    items = db.scalars(select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id)
                       .order_by(PriceUpdateItem.id)).all()
    for n, item in enumerate(items, start=1):
        old = db.get(Article, item.base_article_id)
        art = Article(price_list_id=pl.id, source_row=old.source_row, article_number=old.article_number,
                      article_number_normalized=old.article_number_normalized, manufacturer_id=old.manufacturer_id,
                      manufacturer_raw=old.manufacturer_raw, description=old.description, category=old.category,
                      unit=old.unit, status=old.status)
        db.add(art)
        db.flush()
        cur = item.currency or "EUR"
        for ptype, amount in (("EK", item.final_ek), ("LISTE", item.final_vk)):
            if amount is not None:
                db.add(ArticlePrice(article_id=art.id, price_type=ptype, amount=amount, currency=cur))
    pl.summary = {**pl.summary, "articles": len(items)}
    upd.adopted_list_id = pl.id
    db.flush()
    return pl



# ---------- Ausnahmen für einzelne Artikel ----------

def rule_for_factor(db: Session, m: Manufacturer, factor: Decimal, user) -> Rule:
    """Regel 'EK × Faktor' für den Hersteller (gleiche Rundung wie die Standardregel), vorhandene wiederverwenden."""
    from backend.services.rules import create_rule

    name = f"{m.name} × {de(factor, 0)}"
    existing = db.scalar(select(Rule).where(Rule.name == name, Rule.manufacturer_id == m.id,
                                            Rule.deleted.is_(False)))
    if existing:
        rv = db.scalar(select(RuleVersion).where(RuleVersion.rule_id == existing.id,
                                                 RuleVersion.version == existing.current_version))
        steps = rv.definition.get("steps", [])
        if len(steps) == 1 and steps[0].get("type") == "multiply" and Decimal(str(steps[0]["factor"])) == factor:
            return existing
        raise ValueError(f"Regel „{name}“ existiert, rechnet aber nicht nur EK × {de(factor, 0)} – bitte Regel wählen")
    rounding = {"mode": "HALF_UP", "places": 2, "timing": "STEP"}
    std = db.get(Rule, m.default_rule_id) if m.default_rule_id else None
    if std and not std.deleted:
        rv = db.scalar(select(RuleVersion).where(RuleVersion.rule_id == std.id,
                                                 RuleVersion.version == std.current_version))
        rounding = rv.definition.get("rounding", rounding)
    defn = RuleDefinition.model_validate({"start_price": "EK", "rounding": rounding,
                                          "steps": [{"type": "multiply", "factor": str(factor)}]})
    return create_rule(db, name, m.id, defn, user, "automatisch für Artikel-Ausnahmen angelegt", owner_id=m.owner_id)


def set_article_rule(db: Session, upd: PriceUpdate, items: list[PriceUpdateItem], rule: Rule | None) -> list[str]:
    """Artikel-Ausnahme setzen (rule) bzw. entfernen (None), dauerhaft beim Hersteller, und Positionen neu rechnen."""
    changed = []
    for item in items:
        if not item.article_number or item.manufacturer_id is None:
            continue
        norm = normalize_article_number(item.article_number)
        ex = db.scalar(select(RuleException).where(RuleException.manufacturer_id == item.manufacturer_id,
                                                   RuleException.match_type == "ARTIKEL",
                                                   RuleException.value_normalized == norm))
        if rule is None:
            if ex:
                db.delete(ex)
                changed.append(item.article_number)
        elif ex:
            ex.rule_id = rule.id
            changed.append(item.article_number)
        else:
            db.add(RuleException(manufacturer_id=item.manufacturer_id, match_type="ARTIKEL",
                                 value=item.article_number, value_normalized=norm, rule_id=rule.id,
                                 note="im Jahresabgleich ausgewählt"))
            changed.append(item.article_number)
    db.flush()
    # Momentaufnahme im Abgleich erneuern: Artikel-Ausnahmen aller Hersteller dieses Abgleichs neu einlesen
    mids = set(db.scalars(select(PriceUpdateItem.manufacturer_id).distinct()
                          .where(PriceUpdateItem.update_id == upd.id, PriceUpdateItem.manufacturer_id.is_not(None))))
    upd.exceptions = [ex for ex in upd.exceptions or [] if ex["typ"] != "ARTIKEL"] + [
        ex for mid in sorted(mids) for ex in snapshot_exceptions(db, mid) if ex["typ"] == "ARTIKEL"]
    ctx = _Ctx(db, upd)
    for item in items:
        if item.source_article_id is None or item.status == "NICHT_EINDEUTIG":
            continue  # ohne Herstellerpreis nichts neu zu rechnen; Ausnahme gilt ab dem nächsten Abgleich
        base = db.get(Article, item.base_article_id)
        source = db.get(Article, item.source_article_id)
        row = compute_item(ctx, base, source, item.match_method)
        for k, v in row.items():
            setattr(item, k, v)
        item.reviewed_by = item.reviewed_at = None
    return changed
