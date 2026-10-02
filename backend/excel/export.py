"""Excel-Export eines Vergleichs bzw. einer Kalkulation.

Schutz gegen Formel-Injektion: Jeder Text wird ausdrücklich als Text geschrieben (nie als Formel).
Texte, die mit = + - @ oder Tab/CR beginnen, werden zusätzlich markiert, damit sie auch beim
späteren Bearbeiten in Excel nicht als Formel gelten. Beträge werden als exakte Dezimalzahlen geschrieben.
"""

from __future__ import annotations

import io
from decimal import Decimal

import openpyxl
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.comparison.service import STATUS_LABELS, STATUSES
from backend.services.manufacturers import code_map, with_code
from backend.models.entities import (
    CalculationResult,
    CalculationRun,
    Comparison,
    ComparisonItem,
    ImportMessage,
    Manufacturer,
    PriceList,
    Rule,
)

DANGEROUS_PREFIX = ("=", "+", "-", "@", "\t", "\r")
MONEY_FORMAT = "#,##0.00"
PERCENT_FORMAT = '0.00" %"'
BOLD = Font(bold=True)


class _Sheet:
    def __init__(self, wb, title: str, header: list[str], widths: list[int] | None = None):
        self.ws = wb.create_sheet(title)
        for i, w in enumerate(widths or [], start=1):
            self.ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        self.ws.freeze_panes = "A2"
        self.row([self._cell(h, bold=True) for h in header])

    def _cell(self, value, fmt: str | None = None, bold: bool = False):
        c = WriteOnlyCell(self.ws, value=value)
        if isinstance(value, str):
            c.data_type = "s"  # nie als Formel
            if value.startswith(DANGEROUS_PREFIX):
                c.alignment = Alignment(horizontal="left")
                c.quotePrefix = True  # Excel behandelt den Inhalt dauerhaft als Text
        if fmt:
            c.number_format = fmt
        if bold:
            c.font = BOLD
        return c

    def row(self, values: list) -> None:
        self.ws.append([v if isinstance(v, Cell) else self._cell(v) for v in values])

    def money(self, v):
        return self._cell(v, MONEY_FORMAT) if isinstance(v, Decimal) else self._cell(v)

    def percent(self, v):
        return self._cell(v, PERCENT_FORMAT) if isinstance(v, Decimal) else self._cell(v)


ITEM_HEADER = ["Artikelnummer", "Original-Nr.", "Alte Artikelnummer", "Hersteller", "Bezeichnung", "Kategorie", "Staffel ab",
               "Preis alt", "Preis neu", "Währung", "Differenz", "Differenz %", "Status", "Zuordnung", "Hinweis"]
ITEM_WIDTHS = [18, 16, 18, 18, 40, 18, 10, 12, 12, 9, 12, 12, 16, 14, 50]


def _item_row(sh: _Sheet, i: ComparisonItem, mfr: dict, codes: dict) -> None:
    code = codes.get(i.manufacturer_id)
    old_nr = with_code(i.old_article.article_number, codes.get(i.old_article.manufacturer_id)) if i.old_article else None
    new_nr = with_code(i.article_number, code)
    hint = " ".join(filter(None, [
        i.note,
        f"Geändert: {', '.join(i.changed_fields)}" if i.changed_fields else None,
        ("Kandidaten: " + ", ".join(f"{with_code(c['number'], code)} ({c['score']})" for c in i.candidates))
        if i.candidates else None,
    ]))
    sh.row([new_nr, i.article_number, old_nr if old_nr != new_nr else None, mfr.get(i.manufacturer_id),
            i.description, i.category, i.min_quantity, sh.money(i.old_amount), sh.money(i.new_amount), i.currency,
            sh.money(i.difference), sh.percent(i.difference_percent), STATUS_LABELS.get(i.status, i.status),
            i.match_method, hint or None])


def _calc_sheet(wb, db: Session, run: CalculationRun | None, title: str = "Kalkulation") -> None:
    sh = _Sheet(wb, title, ["Zeile", "Artikelnummer", "Original-Nr.", "Bezeichnung", "Ausgangspreis", "Ergebnis",
                            "Währung", "Status", "Fehler", "Rechenweg"], [8, 18, 16, 40, 14, 14, 9, 10, 40, 90])
    codes = code_map(db)
    if run is None:
        sh.row(["Keine Kalkulation für die neue Liste vorhanden."])
        return
    rule = db.get(Rule, run.rule_version.rule_id)
    sh.row([f"Regel {rule.name} v{run.rule_version.version}, Menge {run.quantity}, berechnet {run.created_at:%d.%m.%Y %H:%M} UTC"])
    stmt = (select(CalculationResult).where(CalculationResult.run_id == run.id)
            .options(selectinload(CalculationResult.article)).order_by(CalculationResult.id))
    for r in db.scalars(stmt):
        steps = []
        for t in r.trace:
            part = f"{t.get('nr')}. {t.get('text') or t.get('typ')}"
            if t.get("operand"):
                part += f" {t['operand']}"
            if t.get("basis_wert"):
                part += f" (Basis {t['basis_wert']})"
            if t.get("betrag"):
                part += f" Betrag {t['betrag']}"
            part += f" = {t.get('ergebnis')}"
            steps.append(part)
        sh.row([r.article.source_row, with_code(r.article.article_number, codes.get(r.article.manufacturer_id)),
                r.article.article_number, r.article.description, sh.money(r.start_amount),
                sh.money(r.result_amount), r.currency, r.status, r.error, " | ".join(steps)])


def export_comparison(db: Session, cmp: Comparison) -> bytes:
    mfr = {m.id: m.name for m in db.scalars(select(Manufacturer))}
    codes = code_map(db)
    items = db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp.id)
                       .options(selectinload(ComparisonItem.old_article)).order_by(ComparisonItem.id)).all()
    wb = openpyxl.Workbook(write_only=True)

    s = cmp.summary or {}
    summary = _Sheet(wb, "Zusammenfassung", ["Angabe", "Wert"], [34, 60])
    for label, value in [
        ("Alte Liste", f"{cmp.old_list.name} ({cmp.old_list.source_file})"),
        ("Neue Liste", f"{cmp.new_list.name} ({cmp.new_list.source_file})"),
        ("Hersteller", mfr.get(cmp.manufacturer_id, "alle")),
        ("Verglichener Preis", cmp.price_type + (f" (Regel-Version v{cmp.rule_version.version})" if cmp.rule_version else "")),
        ("Menge", cmp.quantity),
        ("Berechnet (UTC)", f"{(cmp.updated_at or cmp.created_at):%d.%m.%Y %H:%M}"),
        ("Analysiert", s.get("analysiert", 0)),
    ] + [(STATUS_LABELS[st], s.get(st, 0)) for st in STATUSES]:
        summary.row([label, value])

    def items_sheet(title: str, wanted) -> None:
        sh = _Sheet(wb, title, ITEM_HEADER, ITEM_WIDTHS)
        for i in items:
            if wanted(i):
                _item_row(sh, i, mfr, codes)

    items_sheet("Alle Artikel", lambda i: True)
    items_sheet("Preisänderungen", lambda i: i.status in ("PREIS_ERHOEHT", "PREIS_GESENKT"))
    items_sheet("Neue Artikel", lambda i: i.status == "NEUER_ARTIKEL")
    items_sheet("Entfallene Artikel", lambda i: i.status == "ENTFALLENER_ARTIKEL")
    items_sheet("Unklare Zuordnungen", lambda i: i.status == "NICHT_EINDEUTIG")

    run = db.scalar(select(CalculationRun).where(CalculationRun.price_list_id == cmp.new_price_list_id)
                    .options(selectinload(CalculationRun.rule_version)).order_by(CalculationRun.id.desc()).limit(1))
    _calc_sheet(wb, db, run)

    errors = _Sheet(wb, "Fehler", ["Quelle", "Zeile", "Artikelnummer", "Spalte", "Code", "Meldung"],
                    [22, 8, 18, 18, 22, 80])
    for i in items:
        if i.status == "FEHLER":
            errors.row(["Vergleich", None, with_code(i.article_number, codes.get(i.manufacturer_id)), None,
                        "VERGLEICH", i.note])
    for label, list_id in (("Import alte Liste", cmp.old_price_list_id), ("Import neue Liste", cmp.new_price_list_id)):
        for m in db.scalars(select(ImportMessage).where(ImportMessage.price_list_id == list_id,
                                                        ImportMessage.level == "FEHLER")
                            .order_by(ImportMessage.source_row)):
            errors.row([label, m.source_row, None, m.column, m.code, m.text])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_calculation(db: Session, run: CalculationRun) -> bytes:
    wb = openpyxl.Workbook(write_only=True)
    pl = db.get(PriceList, run.price_list_id)
    info = _Sheet(wb, "Zusammenfassung", ["Angabe", "Wert"], [30, 60])
    rule = db.get(Rule, run.rule_version.rule_id)
    for label, value in [("Preisliste", f"{pl.name} ({pl.source_file})"), ("Regel", f"{rule.name} v{run.rule_version.version}"),
                         ("Menge", run.quantity), ("Artikel", (run.summary or {}).get("artikel")),
                         ("Berechnet", (run.summary or {}).get("OK")), ("Fehler", (run.summary or {}).get("FEHLER"))]:
        info.row([label, value])
    _calc_sheet(wb, db, run)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_price_update(db: Session, upd) -> bytes:
    """Neue Preisliste: nur unsere Artikel, Herstellerpreis und kalkulierter Preis."""
    from backend.comparison.update import STATUS_LABELS as UL
    from backend.models.entities import PriceUpdateItem

    codes = code_map(db)
    mfr = {m.id: m.name for m in db.scalars(select(Manufacturer))}
    items = db.scalars(select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id)
                       .order_by(PriceUpdateItem.id)).all()
    rule_label = None
    if upd.rule_version:
        rule_label = f"{db.get(Rule, upd.rule_version.rule_id).name} v{upd.rule_version.version}"
    wb = openpyxl.Workbook(write_only=True)
    s = upd.summary or {}
    info = _Sheet(wb, "Zusammenfassung", ["Angabe", "Wert"], [36, 60])
    for label, value in [
        ("Unsere Liste (Artikelauswahl)", f"{upd.base_list.name} ({upd.base_list.source_file})"),
        ("Herstellerliste (neue Preise)", f"{upd.source_list.name} ({upd.source_list.source_file})"),
        ("Preisart", upd.price_type), ("Regel", rule_label or "keine"), ("Menge", upd.quantity),
        ("Artikel", s.get("artikel", 0)),
    ] + [(UL[k], s.get(k, 0)) for k in UL] + [
        ("Nur beim Hersteller (ignoriert)", s.get("ignoriert_nur_beim_hersteller", 0))]:
        info.row([label, value])

    header = ["Artikelnummer", "Original-Nr.", "Hersteller", "Bezeichnung", "Preis alt", "Preis Hersteller neu",
              "Kalkulierter Preis", "Währung", "Differenz", "Differenz %", "Status", "Hinweis"]
    widths = [18, 16, 18, 40, 12, 16, 16, 9, 12, 12, 22, 60]
    main = _Sheet(wb, "Neue Preisliste", header, widths)
    open_items = _Sheet(wb, "Zu prüfen", header, widths)
    for i in items:
        row = [with_code(i.article_number, codes.get(i.manufacturer_id)), i.article_number,
               mfr.get(i.manufacturer_id), i.description, main.money(i.old_amount), main.money(i.new_amount),
               main.money(i.calculated_amount), i.currency, main.money(i.difference),
               main.percent(i.difference_percent), UL.get(i.status, i.status), i.note]
        main.row(row)
        if i.status in ("NICHT_IN_HERSTELLERLISTE", "NICHT_EINDEUTIG", "FEHLER"):
            open_items.row([open_items._cell(v.value, v.number_format) if isinstance(v, Cell) else v for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
