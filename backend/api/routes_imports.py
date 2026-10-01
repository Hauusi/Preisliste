from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.excel.columns import FIELDS, PRICE_FIELDS
from backend.excel.numbers import SUPPORTED_CURRENCIES
from backend.excel.reader import ExcelRejected
from backend.models.entities import Manufacturer, PriceList, User
from backend.services.audit import audit
from backend.services.imports import build_preview, confirm_import, save_upload, stored_path

router = APIRouter()


def _draft(db: Session, list_id: int) -> PriceList:
    pl = db.get(PriceList, list_id)
    if pl is None:
        raise HTTPException(404, "Preisliste nicht gefunden")
    if pl.status != "ENTWURF":
        raise HTTPException(409, "Diese Liste wurde bereits importiert")
    return pl


@router.get("/import")
def upload_form(request: Request, _user: User = Depends(current_user)):
    return render(request, "import_upload.html", {"error": None})


@router.post("/import", dependencies=[Depends(check_csrf)])
def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    try:
        pl = save_upload(db, file.file, file.filename or "", user, settings)
    except ExcelRejected as exc:
        audit(db, user, "upload_abgelehnt", details={"datei": (file.filename or "")[:200], "grund": str(exc)},
              ip=client_ip(request))
        return render(request, "import_upload.html", {"error": str(exc)}, status_code=400)
    audit(db, user, "upload", "price_list", pl.id, {"datei": pl.source_file}, client_ip(request))
    return RedirectResponse(f"/import/{pl.id}", status_code=303)


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@router.get("/import/{list_id}")
def preview(request: Request, list_id: int, sheet: str | None = None, header_row: str | None = None,
            header_rows: str | None = None, db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings), _user: User = Depends(current_user)):
    pl = _draft(db, list_id)
    try:
        pv = build_preview(db, pl, settings, sheet, _int(header_row), _int(header_rows))
    except ExcelRejected as exc:
        raise HTTPException(400, str(exc))
    manufacturers = list(db.scalars(select(Manufacturer).order_by(Manufacturer.name)))
    return render(request, "import_preview.html", {
        "pl": pl, "pv": pv, "fields": FIELDS, "currencies": SUPPORTED_CURRENCIES,
        "manufacturers": manufacturers, "error": None,
    })


@router.post("/import/{list_id}/confirm", dependencies=[Depends(check_csrf)])
async def confirm(request: Request, list_id: int, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    pl = _draft(db, list_id)
    form = await request.form()
    sheet = str(form.get("sheet") or "")
    header_row = _int(form.get("header_row"))
    header_rows = _int(form.get("header_rows"), 1)
    mapping: dict[str, int] = {}
    separators: dict[int, str | None] = {}
    errors = []
    for key, value in form.multi_items():
        m = re.fullmatch(r"col_(\d+)", key)
        if m and value:
            if value not in FIELDS:
                errors.append(f"Unbekanntes Feld {value!r}")
            elif value in mapping:
                errors.append(f"{FIELDS[value]} ist mehreren Spalten zugeordnet")
            else:
                mapping[value] = int(m.group(1))
        m = re.fullmatch(r"sep_(\d+)", key)
        if m and value in (",", "."):
            separators[int(m.group(1))] = value
    if "article_number" not in mapping:
        errors.append("Artikelnummer-Spalte zuordnen")
    if not any(f in mapping for f in PRICE_FIELDS):
        errors.append("Mindestens eine Preisspalte zuordnen (EK, Listenpreis oder UVP)")
    manufacturer_id = _int(form.get("manufacturer_id"))
    new_manufacturer = str(form.get("new_manufacturer") or "").strip()[:200] or None
    if "manufacturer" not in mapping and manufacturer_id is None and not new_manufacturer:
        errors.append("Hersteller wählen oder neu anlegen (oder Herstellerspalte zuordnen)")
    currency = str(form.get("currency") or "") or None
    if currency is not None and currency not in SUPPORTED_CURRENCIES:
        errors.append("Ungültige Währung")
    valid_from = str(form.get("valid_from") or "") or None
    if valid_from and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valid_from):
        errors.append("Gültig ab: Datum im Format JJJJ-MM-TT")
    if header_row is None:
        errors.append("Kopfzeile angeben")

    if not errors:
        savepoint = db.begin_nested()
        try:
            summary = confirm_import(
                db, pl, settings, sheet_name=sheet, header_row=header_row, header_rows=header_rows,
                mapping=mapping, manufacturer_id=manufacturer_id, new_manufacturer=new_manufacturer,
                currency=currency, decimal_separators=separators, valid_from=valid_from,
            )
        except (ValueError, ExcelRejected) as exc:
            savepoint.rollback()
            errors.append(str(exc))
        else:
            savepoint.commit()
            audit(db, user, "import", "price_list", pl.id,
                  {"mapping": mapping, "summary": summary}, client_ip(request))
            return RedirectResponse(f"/listen/{pl.id}", status_code=303)

    pv = build_preview(db, pl, settings, sheet or None, header_row, header_rows)
    manufacturers = list(db.scalars(select(Manufacturer).order_by(Manufacturer.name)))
    return render(request, "import_preview.html", {
        "pl": pl, "pv": pv, "fields": FIELDS, "currencies": SUPPORTED_CURRENCIES,
        "manufacturers": manufacturers, "error": "; ".join(errors),
    }, status_code=400)


@router.post("/import/{list_id}/verwerfen", dependencies=[Depends(check_csrf)])
def discard(request: Request, list_id: int, db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    pl = _draft(db, list_id)
    stored_path(pl, settings).unlink(missing_ok=True)
    audit(db, user, "entwurf_verworfen", "price_list", pl.id, {"datei": pl.source_file}, client_ip(request))
    db.delete(pl)
    return RedirectResponse("/listen", status_code=303)
