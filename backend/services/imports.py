"""Import-Ablauf: Hochladen -> Vorschau/Erkennung -> Bestätigen -> Import."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.excel import columns as col
from backend.excel.importer import ImportConfig, run_import
from backend.excel.reader import ExcelRejected, SheetData, check_file, list_sheets, read_sheet
from backend.models.entities import Manufacturer, PriceList, User, utcnow
from backend.services.manufacturers import suggest_by_code

PREVIEW_ROWS = 20
DETECTION_ROWS = 600


class UploadTooLarge(ExcelRejected):
    pass


def save_upload(db: Session, stream, original_name: str, user: User, settings: Settings) -> PriceList:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(original_name or "datei.xlsx").name[:200]
    # Endung .xlsx nötig, weil openpyxl andere Endungen ablehnt; Inhalt wird vorher geprüft
    target = settings.upload_dir / f"{secrets.token_hex(16)}.xlsx"
    limit = settings.max_upload_mb * 1024 * 1024
    sha = hashlib.sha256()
    size = 0
    try:
        with open(target, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise UploadTooLarge(f"Datei ist größer als {settings.max_upload_mb} MB.")
                sha.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ExcelRejected("Die Datei ist leer.")
        check_file(target, safe_name, settings.max_uncompressed_mb * 1024 * 1024, settings.max_zip_entries)
        list_sheets(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    final = target
    pl = PriceList(
        name=Path(safe_name).stem,
        source_file=safe_name,
        stored_file=final.name,
        file_sha256=sha.hexdigest(),
        status="ENTWURF",
        uploaded_by=user.id,
    )
    db.add(pl)
    db.flush()
    return pl


def stored_path(pl: PriceList, settings: Settings) -> Path:
    path = (settings.upload_dir / pl.stored_file).resolve()
    if path.parent != settings.upload_dir.resolve():
        raise ExcelRejected("Ungültiger Dateipfad")
    return path


@dataclass
class Preview:
    sheets: list[str]
    sheet: SheetData
    detection: col.Detection
    sample_rows: list[list]
    manufacturer_suggestion: int | None
    duplicate_of: PriceList | None
    hidden_sheet: bool
    prefix_suggestion: bool = False


def build_preview(db: Session, pl: PriceList, settings: Settings, sheet_name: str | None = None,
                  header_row: int | None = None, header_rows: int | None = None) -> Preview:
    path = stored_path(pl, settings)
    sheets = list_sheets(path)
    sheet = read_sheet(path, sheet_name or sheets[0], max_rows=DETECTION_ROWS)
    synonyms = col.load_synonyms(settings.config_dir)
    detection = col.detect_columns(sheet, synonyms, header_row, header_rows)
    start = detection.header_row
    sample = sheet.rows[start: start + PREVIEW_ROWS]
    known = [(m.id, m.name, m.aliases or []) for m in db.scalars(select(Manufacturer))]
    suggestion = col.suggest_manufacturer(known, pl.source_file, sheet, detection.header_row)
    nr_col = detection.mapping().get("article_number")
    prefix_suggestion = False
    if nr_col is not None:
        by_code = suggest_by_code(db, [r[nr_col] for r in sheet.rows[start:] if nr_col < len(r)])
        if by_code is not None:
            prefix_suggestion = suggestion in (None, by_code)
            suggestion = suggestion or by_code
    dup = db.scalar(
        select(PriceList).where(
            PriceList.file_sha256 == pl.file_sha256,
            PriceList.status == "IMPORTIERT",
            PriceList.id != pl.id,
        )
    )
    return Preview(sheets=sheets, sheet=sheet, detection=detection, sample_rows=sample,
                   manufacturer_suggestion=suggestion, duplicate_of=dup, hidden_sheet=sheet.hidden,
                   prefix_suggestion=prefix_suggestion)


def confirm_import(db: Session, pl: PriceList, settings: Settings, *, sheet_name: str, header_row: int,
                   header_rows: int, mapping: dict[str, int], manufacturer_id: int | None,
                   new_manufacturer: str | None, currency: str | None,
                   decimal_separators: dict[int, str | None], valid_from: str | None, progress=None,
                   strip_prefix: str | None = None) -> dict:
    if pl.status not in ("ENTWURF", "WARTESCHLANGE"):
        raise ValueError("Diese Liste wurde bereits verarbeitet")
    if new_manufacturer:
        name = new_manufacturer.strip()
        existing = db.scalar(select(Manufacturer).where(Manufacturer.name == name))
        if existing is None:
            existing = Manufacturer(name=name, aliases=[])
            db.add(existing)
            db.flush()
        manufacturer_id = existing.id
    if manufacturer_id is not None and db.get(Manufacturer, manufacturer_id) is None:
        raise ValueError("Hersteller nicht gefunden")

    path = stored_path(pl, settings)
    sheet = read_sheet(path, sheet_name)
    if header_row < 1 or header_row > len(sheet.rows):
        raise ValueError("Kopfzeile liegt außerhalb der Tabelle")
    cfg = ImportConfig(
        header_row=header_row,
        mapping=mapping,
        manufacturer_id=manufacturer_id,
        default_currency=currency,
        decimal_separators=decimal_separators,
        valid_from=valid_from,
        strip_prefix=strip_prefix,
    )
    summary = run_import(db, pl.id, sheet, cfg, progress)
    pl.sheet = sheet_name
    pl.header_row = header_row
    pl.column_mapping = {"mapping": mapping, "header_rows": header_rows, "strip_prefix": strip_prefix,
                         "decimal_separators": {str(k): v for k, v in decimal_separators.items()}}
    pl.manufacturer_id = manufacturer_id
    pl.currency = currency
    pl.valid_from = valid_from
    pl.status = "IMPORTIERT"
    pl.summary = summary
    pl.imported_at = utcnow()
    return summary
