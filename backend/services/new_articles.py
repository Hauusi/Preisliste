"""Neue Artikel unterm Jahr in die aktuelle EK/VK-Liste des Herstellers aufnehmen.

Eingabe: eingefügte Zeilen (z. B. aus Excel kopiert): Artikelnummer mit Kürzel, optional Bezeichnung und EK.
- Hersteller wird am Kürzel erkannt (ST123 -> Kürzel ST). Mehrdeutige Kürzel werden nicht geraten.
- EK: aus der Zeile, sonst aus der neuesten Herstellerliste (mit Händlerrabatt/Währung wie im Jahresabgleich).
- VK: Standardregel des Herstellers bzw. eigene Kalkulation des Artikels, mit Gegenrechnung.
Nichts wird gespeichert, bevor die Liste bestätigt ist; beim Speichern wird alles neu geprüft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.comparison.update import (
    REASON_LABELS,
    _Ctx,
    compute_item,
    manufacturer_settings,
    snapshot_exceptions,
)
from backend.excel.importer import normalize_article_number
from backend.excel.numbers import parse_amount
from backend.matching.cascade import strip_zeros
from backend.models.entities import Article, ArticlePrice, Manufacturer, PriceList, PriceUpdate, Rule, RuleVersion

MAX_LINES = 2000
NEW_ARTICLE_REASONS = {"KEIN_ALTER_EK", "KEIN_ALTER_VK"}  # bei neuen Artikeln selbstverständlich


@dataclass
class Row:
    line: int
    raw: str
    number: str | None = None
    description: str | None = None
    manufacturer: Manufacturer | None = None
    target: PriceList | None = None
    source_list: PriceList | None = None
    source_amount: Decimal | None = None
    source_currency: str | None = None
    ek: Decimal | None = None
    vk: Decimal | None = None
    factor: Decimal | None = None
    rule_label: str | None = None
    ek_text: str | None = None
    check_ok: bool | None = None
    category: str | None = None
    errors: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _lists(db: Session, m: Manufacturer, kind: str) -> list[PriceList]:
    lists = db.scalars(select(PriceList).where(PriceList.status == "IMPORTIERT", PriceList.kind == kind)
                       .order_by(PriceList.id.desc())).all()
    out = []
    for pl in lists:
        mids = {pl.manufacturer_id} if pl.manufacturer_id else set(db.scalars(
            select(Article.manufacturer_id).distinct().where(Article.price_list_id == pl.id,
                                                             Article.manufacturer_id.is_not(None))))
        if mids == {m.id}:
            out.append(pl)
    return out


def _find(db: Session, pl: PriceList, m: Manufacturer, norm: str) -> list[Article]:
    stmt = select(Article).where(Article.price_list_id == pl.id).options(selectinload(Article.prices))
    if m.ignore_leading_zeros and norm.isdigit():
        cands = db.scalars(stmt.where(Article.article_number_normalized.like(f"%{norm.lstrip('0') or '0'}"))).all()
        return [a for a in cands if strip_zeros(a.article_number_normalized or "") == strip_zeros(norm)]
    return db.scalars(stmt.where(Article.article_number_normalized == norm)).all()


def parse_lines(text: str) -> list[tuple[int, str, list[str]]]:
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(";"))]
        out.append((n, line.strip()[:300], parts))
    return out


def analyze(db: Session, text: str) -> list[Row]:
    lines = parse_lines(text)
    if len(lines) > MAX_LINES:
        raise ValueError(f"Höchstens {MAX_LINES} Zeilen auf einmal")
    codes = {m.code: m for m in db.scalars(select(Manufacturer).where(Manufacturer.code.is_not(None)))}
    seen: dict[tuple[int, str], int] = {}
    cache: dict = {}
    rows = []
    for n, raw, parts in lines:
        row = Row(n, raw)
        rows.append(row)
        number = parts[0] if parts else ""
        row.description = (parts[1] if len(parts) > 1 else "")[:500] or None
        ek_raw = parts[2] if len(parts) > 2 else ""
        upper = number.upper()
        hits = [c for c in codes if upper.startswith(c) and len(normalize_article_number(number)) > len(c)]
        if not number:
            row.errors.append("Artikelnummer fehlt")
            continue
        if not hits:
            row.errors.append("Kein Hersteller-Kürzel erkannt (Kürzel beim Hersteller hinterlegen)")
            continue
        if len(hits) > 1:
            row.errors.append(f"Kürzel mehrdeutig ({', '.join(sorted(hits))}) – wird nicht geraten")
            continue
        code = hits[0]
        m = row.manufacturer = codes[code]
        rest = number[len(code):].lstrip(" -_./")
        norm = normalize_article_number(rest)
        row.number = rest
        if not norm:
            row.errors.append("Nach dem Kürzel fehlt die Artikelnummer")
            continue
        key = (m.id, strip_zeros(norm) if m.ignore_leading_zeros else norm)
        if key in seen:
            row.errors.append(f"Doppelt eingefügt (schon in Zeile {seen[key]})")
            continue
        seen[key] = n
        if m.id not in cache:
            cache[m.id] = (_lists(db, m, "UNSERE"), _lists(db, m, "HERSTELLER"))
        ours, theirs = cache[m.id]
        if not ours:
            row.errors.append(f"Für {m.name} gibt es noch keine aktuelle EK/VK-Liste (Import als „Unsere Liste“)")
            continue
        row.target = ours[0]
        currencies = set(db.scalars(select(ArticlePrice.currency).distinct().join(Article)
                                    .where(Article.price_list_id == row.target.id)))
        if currencies - {"EUR"}:
            row.errors.append("Aktuelle Liste ist nicht in EUR")
            continue
        if _find(db, row.target, m, norm):
            row.errors.append(f"Steht schon in „{row.target.name}“")
            continue
        rule = db.get(Rule, m.default_rule_id) if m.default_rule_id else None
        if rule is None or rule.deleted:
            row.errors.append(f"{m.name} hat keine Standardregel")
            continue
        rv = db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id,
                                                 RuleVersion.version == rule.current_version))
        st = manufacturer_settings(m)
        upd = PriceUpdate(price_type=st["basis"], rule_version_id=rv.id, quantity=Decimal(1),
                          dealer_discount=st["discount"] if st["basis"] == "UVP" else None,
                          review_threshold=st["threshold"], scope="VOLL", list_currency=st["currency"],
                          exchange_rate=st["rate"] if st["currency"] != "EUR" else None,
                          exceptions=snapshot_exceptions(db, m.id))
        if ek_raw:
            parsed = parse_amount(ek_raw, ",")
            if not parsed.ok or parsed.value is None or parsed.value <= 0:
                row.errors.append(f"EK „{ek_raw[:30]}“ ist keine gültige Zahl größer 0")
                continue
            # EK von Hand: in EUR, ohne Rabatt/Umrechnung
            upd.price_type, upd.dealer_discount, upd.list_currency, upd.exchange_rate = "EK", None, "EUR", None
            source = Article(article_number=rest, article_number_normalized=norm, manufacturer_id=m.id,
                             description=row.description, source_row=0, status="OK",
                             prices=[ArticlePrice(price_type="EK", amount=parsed.value, currency="EUR")])
            row.hints.append("EK aus der eingefügten Zeile")
        else:
            found, where = [], None
            for pl in theirs:
                found = _find(db, pl, m, norm)
                if found:
                    where = pl
                    break
            if not found:
                row.errors.append("Nicht in einer Herstellerliste gefunden – EK in der Zeile mit angeben")
                continue
            if len(found) > 1:
                row.errors.append(f"In „{where.name}“ mehrfach vorhanden – wird nicht geraten")
                continue
            source = found[0]
            row.source_list = where
            if source.article_number and source.article_number != rest:
                row.hints.append(f"Nummer wie in der Herstellerliste: {source.article_number}")
                rest, norm = source.article_number, source.article_number_normalized
                row.number = rest
            row.description = row.description or source.description
            row.category = source.category
        base = Article(article_number=rest, article_number_normalized=norm, manufacturer_id=m.id,
                       description=row.description, source_row=0, status="OK", prices=[])
        result = compute_item(_Ctx(db, upd), base, source, "NEU")
        row.source_amount, row.source_currency = result["source_amount"], result["source_currency"]
        row.rule_label, row.ek_text, row.check_ok = result["rule_label"], result["ek_text"], result["check_ok"]
        row.factor = result["factor"]
        if result["status"] == "FEHLER":
            row.errors.append(result["note"] or "Berechnung nicht möglich")
            continue
        row.ek, row.vk = result["final_ek"], result["final_vk"]
        row.hints += [REASON_LABELS[r] for r in result["reasons"] or [] if r not in NEW_ARTICLE_REASONS]
        if any(r in ("VK_UNTER_EK", "PREIS_NULL") for r in result["reasons"] or []):
            row.errors.append("VK unter EK oder Preis 0 – so nicht aufnehmbar")
    return rows


def add_rows(db: Session, rows: list[Row], selected: set[int]) -> list[tuple[Row, Article]]:
    added = []
    next_row: dict[int, int] = {}
    for row in rows:
        if row.line not in selected or not row.ok:
            continue
        pl = row.target
        if pl.id not in next_row:
            next_row[pl.id] = (db.scalar(select(func.max(Article.source_row)).where(Article.price_list_id == pl.id))
                               or 0) + 1
        art = Article(price_list_id=pl.id, source_row=next_row[pl.id], article_number=row.number,
                      article_number_normalized=normalize_article_number(row.number),
                      manufacturer_id=row.manufacturer.id, description=row.description, category=row.category,
                      status="OK")
        next_row[pl.id] += 1
        db.add(art)
        db.flush()
        db.add(ArticlePrice(article_id=art.id, price_type="EK", amount=row.ek, currency="EUR"))
        db.add(ArticlePrice(article_id=art.id, price_type="LISTE", amount=row.vk, currency="EUR"))
        added.append((row, art))
        if isinstance(pl.summary, dict) and "articles" in pl.summary:
            pl.summary = {**pl.summary, "articles": pl.summary["articles"] + 1}
    db.flush()
    return added
