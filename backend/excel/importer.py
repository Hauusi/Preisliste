"""Bestätigten Import ausführen: Zeilen lesen, prüfen, in die Datenbank schreiben.

Keine stillen Annahmen: jede Auffälligkeit wird als FEHLER, WARNUNG oder UNKLAR gespeichert.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from backend.excel.columns import FIELDS, PRICE_FIELDS, normalize_label
from backend.excel.numbers import (
    SUPPORTED_CURRENCIES,
    ParsedAmount,
    _extract_currency,
    is_empty,
    parse_amount,
    parse_percent,
)
from backend.excel.reader import SheetData
from backend.models.entities import Article, ArticlePrice, ImportMessage, Manufacturer

PRICE_TYPE = {"supplier_price": "EK", "list_price": "LISTE", "rrp": "UVP"}
LEVEL_RANK = {"OK": 0, "WARNUNG": 1, "UNKLAR": 2, "FEHLER": 3}


def normalize_article_number(value: str) -> str:
    """Großschreibung, ohne Leerzeichen, Bindestriche, Punkte, Schrägstriche, Unterstriche.

    Führende Nullen bleiben erhalten (offene Frage F2, wird in Gruppe B konfigurierbar).
    """
    return re.sub(r"[\s\-./_]+", "", value.upper())


def cell_text(value) -> str | None:
    if is_empty(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dt.datetime, dt.date)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    return str(value).strip()


def parse_date(value) -> tuple[str | None, str | None]:
    if is_empty(value):
        return None, None
    if isinstance(value, dt.datetime):
        return value.date().isoformat(), None
    if isinstance(value, dt.date):
        return value.isoformat(), None
    text = str(value).strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat(), None
        except ValueError:
            pass
    return None, f"Datum nicht lesbar: {text!r}"


@dataclass
class ImportConfig:
    header_row: int
    mapping: dict[str, int]  # Feld -> Spaltenindex (0-basiert)
    manufacturer_id: int | None  # Listen-Hersteller, falls keine Herstellerspalte
    default_currency: str | None
    decimal_separators: dict[int, str | None] = field(default_factory=dict)
    valid_from: str | None = None
    strip_prefix: str | None = None  # Firmenkürzel, das in der Datei schon vor der Nummer steht


@dataclass
class RowResult:
    source_row: int
    number: str | None
    manufacturer_key: str | None
    manufacturer_raw: str | None
    description: str | None
    category: str | None
    unit: str | None
    prices: list[dict]
    quantity: Decimal | None
    messages: list[tuple[str, str, str, str | None]]  # (level, code, text, column)

    @property
    def status(self) -> str:
        worst = "OK"
        for level, *_ in self.messages:
            if LEVEL_RANK[level] > LEVEL_RANK[worst]:
                worst = level
        return worst


class _Manufacturers:
    """Herstellerzuordnung über Name/Alias; unbekannte Namen aus der Herstellerspalte werden angelegt."""

    def __init__(self, db: Session, owner_id: int | None):
        self.db = db
        self.owner_id = owner_id
        self.by_key: dict[str, int] = {}
        self.created: list[str] = []
        # nur Hersteller des Listen-Besitzers (jeder Benutzer hat eigene Hersteller)
        for m in db.scalars(select(Manufacturer).where(Manufacturer.owner_id == owner_id)):
            for n in [m.name, *(m.aliases or [])]:
                self.by_key[self.key(n)] = m.id

    @staticmethod
    def key(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", normalize_label(name))

    def resolve(self, raw: str) -> int:
        k = self.key(raw)
        if k not in self.by_key:
            m = Manufacturer(name=raw.strip(), aliases=[], owner_id=self.owner_id)
            self.db.add(m)
            self.db.flush()
            self.by_key[k] = m.id
            self.created.append(m.name)
        return self.by_key[k]


def _get(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _amount_message(parsed: ParsedAmount, label: str) -> tuple[str, str, str, str]:
    return (parsed.level or "FEHLER", parsed.code or "KEIN_BETRAG", f"{label}: {parsed.message}", label)


def process_row(sheet: SheetData, row_idx: int, row: list, cfg: ImportConfig) -> RowResult | str | None:
    """Eine Datenzeile prüfen. None = leere Zeile, 'SKIP' = Zwischenzeile ohne Nummer und Preis."""
    m = cfg.mapping
    excel_row = row_idx + 1
    mapped_values = [_get(row, i) for i in m.values()]
    if all(is_empty(v) for v in mapped_values):
        return None

    messages: list[tuple[str, str, str, str | None]] = []
    for fld, col in m.items():
        if (excel_row, col + 1) in sheet.formula_without_cache:
            messages.append((
                "WARNUNG", "FORMEL_OHNE_WERT",
                f"{FIELDS[fld]}: Formel ohne gespeichertes Ergebnis (Datei in Excel öffnen und speichern)",
                FIELDS[fld],
            ))

    number = cell_text(_get(row, m.get("article_number")))
    if number and cfg.strip_prefix:
        if number.upper().startswith(cfg.strip_prefix) and len(number) > len(cfg.strip_prefix):
            number = number[len(cfg.strip_prefix):]
        else:
            messages.append(("WARNUNG", "KUERZEL_FEHLT",
                             f"Artikelnummer beginnt nicht mit dem Kürzel {cfg.strip_prefix}, unverändert übernommen",
                             FIELDS["article_number"]))
    price_cells = {f: _get(row, m[f]) for f in PRICE_FIELDS if f in m}
    if number is None and all(is_empty(v) for v in price_cells.values()):
        return "SKIP"
    if number is None:
        messages.append(("FEHLER", "ARTIKELNUMMER_FEHLT", "Keine Artikelnummer", FIELDS["article_number"]))

    # Währung der Zeile: Währungsspalte, sonst Listenwährung
    row_currency = cfg.default_currency
    if "currency" in m:
        raw_cur = cell_text(_get(row, m["currency"]))
        if raw_cur:
            _, cur, unknown = _extract_currency(raw_cur)
            if cur is None:
                messages.append(("FEHLER", "WAEHRUNG_UNBEKANNT", f"Unbekannte Währung: {raw_cur!r}", FIELDS["currency"]))
                row_currency = None
            else:
                row_currency = cur

    def amount(fld: str) -> Decimal | None:
        val = _get(row, m.get(fld))
        if is_empty(val):
            return None
        parsed = parse_amount(val, cfg.decimal_separators.get(m[fld]))
        if not parsed.ok:
            messages.append(_amount_message(parsed, FIELDS[fld]))
            return None
        return parsed.value

    quantity = amount("quantity") if "quantity" in m else None
    if quantity is not None and quantity <= 0:
        messages.append(("FEHLER", "MENGE_UNGUELTIG", f"Menge muss größer 0 sein: {quantity}", FIELDS["quantity"]))
        quantity = None

    discount = None
    if "discount" in m and not is_empty(_get(row, m["discount"])):
        parsed = parse_percent(_get(row, m["discount"]), cfg.decimal_separators.get(m["discount"]))
        if not parsed.ok:
            messages.append(_amount_message(parsed, FIELDS["discount"]))
        elif not (Decimal(0) <= parsed.value <= Decimal(100)):
            messages.append(("FEHLER", "RABATT_UNGUELTIG", f"Rabatt außerhalb 0-100 %: {parsed.value}", FIELDS["discount"]))
        else:
            discount = parsed.value

    transport = amount("transport_cost") if "transport_cost" in m else None

    valid_from = cfg.valid_from
    if "valid_from" in m:
        date_val, date_err = parse_date(_get(row, m["valid_from"]))
        if date_err:
            messages.append(("WARNUNG", "DATUM_UNGUELTIG", date_err, FIELDS["valid_from"]))
        valid_from = date_val or valid_from

    prices: list[dict] = []
    for fld, val in price_cells.items():
        if is_empty(val):
            continue
        parsed = parse_amount(val, cfg.decimal_separators.get(m[fld]))
        if not parsed.ok:
            messages.append(_amount_message(parsed, FIELDS[fld]))
            continue
        currency = parsed.currency or row_currency
        if parsed.currency and row_currency and parsed.currency != row_currency and "currency" in m:
            messages.append(("FEHLER", "WAEHRUNG_WIDERSPRUCH",
                             f"{FIELDS[fld]}: Währung {parsed.currency} passt nicht zu {row_currency}", FIELDS[fld]))
            continue
        if currency is None or currency not in SUPPORTED_CURRENCIES:
            messages.append(("FEHLER", "WAEHRUNG_FEHLT",
                             f"{FIELDS[fld]}: Währung unbekannt (keine Annahme)", FIELDS[fld]))
            continue
        if parsed.value < 0:
            messages.append(("FEHLER", "PREIS_NEGATIV", f"{FIELDS[fld]}: negativer Preis {parsed.value}", FIELDS[fld]))
            continue
        if parsed.value == 0:
            messages.append(("WARNUNG", "PREIS_NULL", f"{FIELDS[fld]}: Preis ist 0", FIELDS[fld]))
        prices.append({
            "price_type": PRICE_TYPE[fld],
            "amount": parsed.value,
            "currency": currency,
            "min_quantity": quantity,
            "discount_percent": discount,
            "transport_cost": transport,
            "valid_from": valid_from,
        })
    if not prices and not any(code.startswith(("WAEHRUNG", "KEIN_BETRAG", "MEHRDEUTIG", "PREIS_NEG"))
                              for _, code, _, _ in messages):
        messages.append(("FEHLER", "PREIS_FEHLT", "Kein Preis vorhanden", None))

    manufacturer_raw = cell_text(_get(row, m.get("manufacturer"))) if "manufacturer" in m else None
    if "manufacturer" in m and manufacturer_raw is None and cfg.manufacturer_id is None:
        messages.append(("FEHLER", "HERSTELLER_FEHLT", "Kein Hersteller", FIELDS["manufacturer"]))

    return RowResult(
        source_row=excel_row,
        number=number,
        manufacturer_key=_Manufacturers.key(manufacturer_raw) if manufacturer_raw else None,
        manufacturer_raw=manufacturer_raw,
        description=cell_text(_get(row, m.get("description"))),
        category=cell_text(_get(row, m.get("category"))),
        unit=cell_text(_get(row, m.get("unit"))),
        prices=prices,
        quantity=quantity,
        messages=messages,
    )


def run_import(db: Session, price_list_id: int, sheet: SheetData, cfg: ImportConfig, progress=None) -> dict:
    """Schreibt Artikel, Preise und Meldungen. Gibt die Zusammenfassung zurück.

    progress(erledigt, gesamt) wird alle 2000 Zeilen aufgerufen und darf zum Abbruch eine Ausnahme werfen
    (vor dem Schreiben, es entstehen keine halben Importe).
    """
    if "article_number" not in cfg.mapping:
        raise ValueError("Artikelnummer-Spalte muss zugeordnet sein")
    if not any(f in cfg.mapping for f in PRICE_FIELDS):
        raise ValueError("Mindestens eine Preisspalte muss zugeordnet sein")
    if "manufacturer" not in cfg.mapping and cfg.manufacturer_id is None:
        raise ValueError("Hersteller fehlt: Herstellerspalte zuordnen oder Hersteller wählen")
    if cfg.default_currency is not None and cfg.default_currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Nicht unterstützte Währung: {cfg.default_currency}")

    from backend.models.entities import PriceList

    manufacturers = _Manufacturers(db, db.get(PriceList, price_list_id).uploaded_by)
    results: list[RowResult] = []
    list_messages: list[dict] = []
    empty_rows = 0
    total_rows = len(sheet.rows) - cfg.header_row
    for idx in range(cfg.header_row, len(sheet.rows)):
        if progress and (idx - cfg.header_row) % 2000 == 0:
            progress(idx - cfg.header_row, total_rows)
        res = process_row(sheet, idx, sheet.rows[idx], cfg)
        if res is None:
            empty_rows += 1
        elif res == "SKIP":
            list_messages.append({
                "price_list_id": price_list_id, "source_row": idx + 1, "column": None,
                "level": "WARNUNG", "code": "ZEILE_UEBERSPRUNGEN",
                "text": "Zeile ohne Artikelnummer und Preis übersprungen (Zwischenüberschrift?)",
            })
        else:
            results.append(res)

    # Hersteller auflösen
    for r in results:
        if r.manufacturer_raw:
            r.manufacturer_key = str(manufacturers.resolve(r.manufacturer_raw))
        elif cfg.manufacturer_id is not None:
            r.manufacturer_key = str(cfg.manufacturer_id)

    # Gleiche Artikelnummer: Staffel (verschiedene Mengen) oder Dublette
    groups: dict[tuple, list[RowResult]] = defaultdict(list)
    for r in results:
        if r.number:
            groups[(r.manufacturer_key, normalize_article_number(r.number))].append(r)
    merged_into: dict[int, RowResult] = {}
    for rows in groups.values():
        if len(rows) < 2:
            continue
        quantities = [r.quantity for r in rows]
        is_tier = "quantity" in cfg.mapping and None not in quantities and len(set(quantities)) == len(quantities)
        if is_tier:
            head = rows[0]
            for other in rows[1:]:
                head.prices.extend(other.prices)
                head.messages.extend(other.messages)
                if other.description and head.description and other.description != head.description:
                    head.messages.append(("WARNUNG", "STAFFEL_BEZEICHNUNG",
                                          f"Staffelzeile {other.source_row} hat abweichende Bezeichnung", None))
                merged_into[id(other)] = head
        else:
            lines = ", ".join(str(r.source_row) for r in rows)
            for r in rows:
                r.messages.append(("WARNUNG", "DOPPELT", f"Artikelnummer mehrfach in der Liste (Zeilen {lines})",
                                   FIELDS["article_number"]))

    next_article = (db.scalar(select(func.max(Article.id))) or 0) + 1
    next_price = (db.scalar(select(func.max(ArticlePrice.id))) or 0) + 1
    article_rows, price_rows = [], []
    counts = defaultdict(int)
    for r in results:
        if id(r) in merged_into:
            continue
        aid = next_article
        next_article += 1
        status = r.status
        counts[status] += 1
        article_rows.append({
            "id": aid,
            "price_list_id": price_list_id,
            "source_row": r.source_row,
            "article_number": r.number,
            "article_number_normalized": normalize_article_number(r.number) if r.number else None,
            "manufacturer_id": int(r.manufacturer_key) if r.manufacturer_key else None,
            "manufacturer_raw": r.manufacturer_raw,
            "description": r.description,
            "category": r.category,
            "unit": r.unit,
            "status": status,
        })
        for p in r.prices:
            price_rows.append({"id": next_price, "article_id": aid, **p})
            next_price += 1
        for level, code, text, column in r.messages:
            list_messages.append({
                "price_list_id": price_list_id, "source_row": r.source_row, "column": column,
                "level": level, "code": code, "text": text,
            })

    if article_rows:
        db.execute(insert(Article), article_rows)
    if price_rows:
        db.execute(insert(ArticlePrice), price_rows)
    if list_messages:
        db.execute(insert(ImportMessage), list_messages)

    msg_counts = defaultdict(int)
    for m in list_messages:
        msg_counts[m["level"]] += 1
    return {
        "articles": len(article_rows),
        "prices": len(price_rows),
        "empty_rows": empty_rows,
        "status": {k: counts.get(k, 0) for k in LEVEL_RANK},
        "messages": {k: msg_counts.get(k, 0) for k in ("FEHLER", "UNKLAR", "WARNUNG")},
        "manufacturers_created": manufacturers.created,
    }
