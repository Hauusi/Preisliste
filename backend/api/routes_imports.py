from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.services.access import get_visible
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.excel.columns import FIELDS, PRICE_FIELDS
from backend.excel.numbers import SUPPORTED_CURRENCIES
from backend.excel.reader import ExcelRejected
from backend.models.entities import Manufacturer, PriceList, User
from backend.services.audit import audit
from backend.jobs.runner import enqueue
from backend.models.entities import Job
from backend.services.imports import build_preview, save_upload, stored_path
from backend.services.manufacturers import normalize_code, validate_code

router = APIRouter()


def _draft(db: Session, list_id: int, user: User) -> PriceList:
    pl = get_visible(db, PriceList, list_id, user)
    if pl.status != "ENTWURF":
        raise HTTPException(409, "Diese Liste wurde bereits importiert")
    return pl


@router.get("/import")
def upload_form(request: Request, _user: User = Depends(current_user)):
    return render(request, "import_upload.html", {"error": None, "step": 1})


@router.post("/import", dependencies=[Depends(check_csrf)])
def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    try:
        pl = save_upload(db, file.file, file.filename or "", user, settings)
    except ExcelRejected as exc:
        audit(db, user, "upload_abgelehnt", details={"datei": (file.filename or "")[:200], "grund": str(exc)},
              ip=client_ip(request))
        return render(request, "import_upload.html", {"error": str(exc), "step": 1}, status_code=400)
    audit(db, user, "upload", "price_list", pl.id, {"datei": pl.source_file}, client_ip(request))
    return RedirectResponse(f"/import/{pl.id}", status_code=303)


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def order_split(split: dict, labels: dict[int, str]) -> dict:
    """Alt/neu festlegen: älteres Jahr in der Überschrift = alt, sonst linke Spalte = alt."""
    cols = list(split["columns"])
    years = [re.search(r"(?:19|20)\d{2}", labels.get(c, "")) for c in cols]
    if all(years) and years[0].group(0) != years[1].group(0):
        cols.sort(key=lambda c: re.search(r"(?:19|20)\d{2}", labels[c]).group(0))
    return {**split, "columns": cols, "labels": [labels.get(c, f"Spalte {c + 1}") for c in cols]}


def _ai_columns(db: Session, ki_job: str | None, pl: PriceList, user: User, pv) -> dict | None:
    """KI-Spaltenvorschlag aus einem fertigen Job, nur wenn er zu Liste, Blatt und Kopfzeile passt."""
    job_id = _int(ki_job)
    job = db.get(Job, job_id) if job_id else None
    if not job or job.type != "AI_COLUMNS" or job.status != "FERTIG" or job.params.get("price_list_id") != pl.id:
        return None
    if job.created_by != user.id and user.role != "admin":
        return None
    r = job.result or {}
    if r.get("status") != "OK":
        return {"status": r.get("status"), "message": r.get("message")}
    if r.get("sheet") != pv.sheet.name or r.get("header_row") != pv.detection.header_row:
        return {"status": "UNKLAR", "message": "Vorschlag gehört zu einem anderen Blatt oder einer anderen Kopfzeile"}
    columns = {int(k): v for k, v in (r.get("columns") or {}).items() if v in FIELDS}
    # Vorschläge der KI nur dort vorauswählen, wo Synonyme/Heuristik nichts gefunden haben
    claimed = {c.field for c in pv.detection.columns if c.field}
    for c in pv.detection.columns:
        ai_field = columns.get(c.index)
        if ai_field and c.field is None and ai_field not in claimed:
            c.field, c.source, c.score = ai_field, "ki", 0.3
            claimed.add(ai_field)
    return {"status": "OK", "columns": columns, "manufacturer": r.get("manufacturer"),
            "confidence": r.get("confidence")}


@router.get("/import/{list_id}")
def preview(request: Request, list_id: int, sheet: str | None = None, header_row: str | None = None,
            header_rows: str | None = None, ki_job: str | None = None, db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    pl = _draft(db, list_id, user)
    try:
        pv = build_preview(db, pl, settings, sheet, _int(header_row), _int(header_rows))
    except ExcelRejected as exc:
        raise HTTPException(400, str(exc))
    return render(request, "import_preview.html", {
        "pl": pl, "pv": pv, "fields": FIELDS, "error": None, "ai": _ai_columns(db, ki_job, pl, user, pv),
        "step": 2,
    })


@router.post("/import/{list_id}/ki-spalten", dependencies=[Depends(check_csrf)])
async def ai_columns(request: Request, list_id: int, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    pl = _draft(db, list_id, user)
    form = await request.form()
    header_row = _int(form.get("header_row"))
    if header_row is None or header_row < 1:
        raise HTTPException(400, "Kopfzeile fehlt")
    job = enqueue(db, "AI_COLUMNS", {"price_list_id": pl.id, "sheet": str(form.get("sheet") or ""),
                                     "header_row": header_row, "header_rows": _int(form.get("header_rows"), 1)}, user)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


def _parse_columns(form) -> dict:
    """Schritt 2: Blatt, Kopfzeile und Spaltenzuordnung aus dem Formular lesen und prüfen."""
    mapping: dict[str, int] = {}
    separators: dict[int, str | None] = {}
    assigned: dict[str, list[int]] = {}
    errors = []
    for key, value in form.multi_items():
        m = re.fullmatch(r"col_(\d+)", key)
        if m and value:
            if value not in FIELDS:
                errors.append(f"Unbekanntes Feld {value!r}")
            else:
                assigned.setdefault(value, []).append(int(m.group(1)))
        m = re.fullmatch(r"sep_(\d+)", key)
        if m and value in (",", "."):
            separators[int(m.group(1))] = value
    split = None
    for fld, cols in assigned.items():
        cols.sort()
        mapping[fld] = cols[0]
        if len(cols) == 1:
            continue
        if fld not in PRICE_FIELDS:
            errors.append(f"{FIELDS[fld]} ist mehreren Spalten zugeordnet")
        elif len(cols) > 2:
            errors.append(f"{FIELDS[fld]} ist mehr als zwei Spalten zugeordnet (höchstens zwei: alt und neu)")
        elif split is not None:
            errors.append("Nur eine Preisart darf zwei Spalten haben")
        else:
            split = {"field": fld, "columns": cols}
    if "article_number" not in mapping:
        errors.append("Artikelnummer-Spalte zuordnen")
    if not any(f in mapping for f in PRICE_FIELDS):
        errors.append("Mindestens eine Preisspalte zuordnen (EK, Listenpreis oder UVP)")
    header_row = _int(form.get("header_row"))
    if header_row is None:
        errors.append("Kopfzeile angeben")
    return {"sheet": str(form.get("sheet") or ""), "header_row": header_row,
            "header_rows": _int(form.get("header_rows"), 1), "mapping": mapping, "assigned": assigned,
            "separators": separators, "split": split, "errors": errors}


def _parse_details(db: Session, form, mapping: dict, owner_id: int) -> dict:
    """Schritt 3: Hersteller, Währung, Gültigkeit. Hersteller nur aus denen des Listen-Besitzers."""
    errors = []
    manufacturer_id = _int(form.get("manufacturer_id"))
    new_manufacturer = str(form.get("new_manufacturer") or "").strip()[:200] or None
    new_code = normalize_code(str(form.get("new_manufacturer_code") or ""))
    if new_code and not new_manufacturer:
        errors.append("Kürzel nur zusammen mit einem neuen Hersteller angeben (sonst auf der Seite Hersteller)")
    elif new_manufacturer:
        existing = db.scalar(select(Manufacturer).where(Manufacturer.name == new_manufacturer,
                                                        Manufacturer.owner_id == owner_id))
        code_error = validate_code(db, new_code, existing.id if existing else None, owner_id)
        if code_error:
            errors.append(code_error)
        elif existing and new_code and existing.code and existing.code != new_code:
            errors.append(f"Hersteller {existing.name} hat bereits das Kürzel {existing.code}")
    if "manufacturer" not in mapping and manufacturer_id is None and not new_manufacturer:
        errors.append("Hersteller wählen oder neu anlegen (oder Herstellerspalte zuordnen)")
    chosen = db.get(Manufacturer, manufacturer_id) if manufacturer_id is not None else None
    if manufacturer_id is not None and (chosen is None or chosen.owner_id != owner_id):
        errors.append("Hersteller nicht gefunden")
    currency = str(form.get("currency") or "") or None
    if currency is not None and currency not in SUPPORTED_CURRENCIES:
        errors.append("Ungültige Währung")
    valid_from = str(form.get("valid_from") or "") or None
    if valid_from and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valid_from):
        errors.append("Gültig ab: Datum im Format JJJJ-MM-TT")
    kind = str(form.get("kind") or "") or None
    if kind is not None and kind not in ("UNSERE", "HERSTELLER"):
        errors.append("Art der Liste wählen")
    if kind == "UNSERE" and "supplier_price" not in mapping:
        errors.append("Unsere Liste braucht eine EK-Spalte (Einkaufspreis) – bitte in Schritt 2 zuordnen")
    if kind == "UNSERE" and "list_price" not in mapping:
        errors.append("Unsere Liste braucht eine VK-Spalte (VK / Listenpreis) – bitte in Schritt 2 zuordnen")
    strip_code = form.get("strip_code") == "1"
    if strip_code and "manufacturer" in mapping:
        errors.append("Kürzel abschneiden geht nur mit einem fest gewählten Hersteller, nicht mit Herstellerspalte")
    elif strip_code:
        m = db.get(Manufacturer, manufacturer_id) if manufacturer_id else None
        if not ((m and m.code) or (new_manufacturer and new_code)):
            errors.append("Kürzel abschneiden: Der gewählte Hersteller hat kein Kürzel")
    return {"manufacturer_id": manufacturer_id, "new_manufacturer": new_manufacturer, "new_code": new_code,
            "currency": currency, "valid_from": valid_from, "strip_code": strip_code, "kind": kind,
            "errors": errors}


def _columns_page(request, db, pl, settings, cols: dict, errors: list[str]):
    pv = build_preview(db, pl, settings, cols["sheet"] or None, cols["header_row"], cols["header_rows"])
    # Auswahl des Benutzers beibehalten
    chosen = {c: f for f, cs in cols["assigned"].items() for c in cs}
    for c in pv.detection.columns:
        if chosen:
            c.field = chosen.get(c.index)
    return render(request, "import_preview.html", {
        "pl": pl, "pv": pv, "fields": FIELDS, "error": "; ".join(errors), "step": 2,
    }, status_code=400)


def _details_context(db: Session, pl: PriceList, settings: Settings, cols: dict) -> dict:
    pv = build_preview(db, pl, settings, cols["sheet"] or None, cols["header_row"], cols["header_rows"])
    labels = {c.index: c.label or f"Spalte {c.index + 1}" for c in pv.detection.columns}
    summary = [(FIELDS[f], ", ".join(labels.get(c, f"Spalte {c + 1}") for c in cs))
               for f, cs in cols["assigned"].items()]
    nr_col = cols["mapping"].get("article_number")
    samples = [str(r[nr_col]).strip() for r in pv.sheet.rows[pv.detection.header_row:pv.detection.header_row + 5]
               if nr_col is not None and nr_col < len(r) and r[nr_col] not in (None, "")]
    return {"pl": pl, "pv": pv, "cols": cols, "summary": summary, "fields": FIELDS, "samples": samples,
            "prefixed": pv.manufacturer_suggestion is not None and pv.prefix_suggestion,
            "currencies": SUPPORTED_CURRENCIES, "step": 3,
            "manufacturers": list(db.scalars(select(Manufacturer).where(Manufacturer.owner_id == pl.uploaded_by)
                                             .order_by(Manufacturer.name)))}


def _stored_columns(pl: PriceList) -> dict | None:
    data = pl.column_mapping or {}
    if not data.get("draft"):
        return None
    return {**data, "assigned": {k: list(v) for k, v in data["assigned"].items()},
            "separators": {int(k): v for k, v in data.get("separators", {}).items()}, "errors": []}


@router.post("/import/{list_id}/spalten", dependencies=[Depends(check_csrf)])
async def save_columns(request: Request, list_id: int, db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    """Schritt 2 -> 3: Zuordnung prüfen und im Entwurf merken."""
    pl = _draft(db, list_id, user)
    cols = _parse_columns(await request.form())
    if cols["errors"]:
        return _columns_page(request, db, pl, settings, cols, cols["errors"])
    pl.column_mapping = {"draft": True, **{k: v for k, v in cols.items() if k != "errors"},
                         "separators": {str(k): v for k, v in cols["separators"].items()}}
    return RedirectResponse(f"/import/{pl.id}/hersteller", status_code=303)


@router.get("/import/{list_id}/hersteller")
def details_form(request: Request, list_id: int, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    pl = _draft(db, list_id, user)
    cols = _stored_columns(pl)
    if cols is None:
        return RedirectResponse(f"/import/{pl.id}", status_code=303)
    return render(request, "import_details.html", {**_details_context(db, pl, settings, cols), "error": None})


@router.post("/import/{list_id}/confirm", dependencies=[Depends(check_csrf)])
async def confirm(request: Request, list_id: int, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    """Schritt 3 -> 4: Import als Hintergrundjob starten."""
    pl = _draft(db, list_id, user)
    form = await request.form()
    cols = _parse_columns(form)
    if cols["errors"]:
        return _columns_page(request, db, pl, settings, cols, cols["errors"])
    details = _parse_details(db, form, cols["mapping"], pl.uploaded_by)
    if details["errors"]:
        ctx = _details_context(db, pl, settings, cols)
        return render(request, "import_details.html", {**ctx, "error": "; ".join(details["errors"])},
                      status_code=400)
    mapping, split = cols["mapping"], cols["split"]
    if split:
        labels = {c.index: c.label or f"Spalte {c.index + 1}"
                  for c in build_preview(db, pl, settings, cols["sheet"] or None, cols["header_row"],
                                         cols["header_rows"]).detection.columns}
        split = order_split(split, labels)
        mapping[split["field"]] = split["columns"][0]
    # Import läuft als Hintergrundjob (große Listen dauern länger als eine Web-Anfrage)
    pl.status = "WARTESCHLANGE"
    pl.kind = details["kind"]
    job = enqueue(db, "IMPORT", {
        "price_list_id": pl.id, "sheet": cols["sheet"], "header_row": cols["header_row"],
        "header_rows": cols["header_rows"], "mapping": mapping, "manufacturer_id": details["manufacturer_id"],
        "new_manufacturer": details["new_manufacturer"], "new_manufacturer_code": details["new_code"],
        "split": split, "user_id": user.id, "currency": details["currency"], "strip_code": details["strip_code"],
        "separators": {str(k): v for k, v in cols["separators"].items()}, "valid_from": details["valid_from"],
    }, user)
    audit(db, user, "import_gestartet", "price_list", pl.id, {"mapping": mapping, "job": job.id},
          client_ip(request))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/import/{list_id}/verwerfen", dependencies=[Depends(check_csrf)])
def discard(request: Request, list_id: int, db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    pl = _draft(db, list_id, user)
    stored_path(pl, settings).unlink(missing_ok=True)
    audit(db, user, "entwurf_verworfen", "price_list", pl.id, {"datei": pl.source_file}, client_ip(request))
    db.delete(pl)
    return RedirectResponse("/listen", status_code=303)
