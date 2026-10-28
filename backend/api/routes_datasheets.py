"""Modul „Datenblatt erstellen“: Liste, Editor mit Live-Vorschau, Druck/PDF, Bilder."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.api.templating import templates
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import Datasheet, User, utcnow
from backend.services import datasheets as ds
from backend.services.access import get_visible, is_admin, visible
from backend.services.audit import audit

router = APIRouter()
MAX_JSON_BYTES = 1024 * 1024


def _pages_html(sheet: Datasheet, content: dict) -> tuple[str, int]:
    """A4-Seiten für die Live-Vorschau (gleiche Vorlage wie die Druckansicht, plus Platzhalter) und Seitenzahl."""
    pages = ds.paginate(content, editor=True)
    html = templates.get_template("_datasheet_pages.html").render(
        sheet=sheet, c=ds.normalized(content), pages=pages, footer=ds.FOOTER, editor=True)
    return html, len(pages)


async def _json(request: Request) -> dict:
    if int(request.headers.get("content-length") or 0) > MAX_JSON_BYTES:
        raise HTTPException(413, "Inhalt zu groß")
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Ungültige Daten")
    if not isinstance(data, dict):
        raise HTTPException(400, "Ungültige Daten")
    return data


@router.get("/datenblatt")
def overview(request: Request, error: str | None = None, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    sheets = db.scalars(visible(select(Datasheet).order_by(Datasheet.updated_at.desc()), Datasheet, user)).all()
    owners = {u.id: u.username for u in db.scalars(select(User))} if is_admin(user) else {}
    return render(request, "datasheets.html", {"portal": True, "sheets": sheets, "owners": owners, "error": error})


@router.get("/datenblatt/neu")
def new_form():
    return RedirectResponse("/datenblatt", status_code=303)


@router.post("/datenblatt/neu", dependencies=[Depends(check_csrf)])
async def create(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    content = ds.empty_content()
    content["kopf"] = {"titel": str(form.get("titel") or "").strip()[:60],
                       "untertitel": str(form.get("untertitel") or "").strip()[:80]}
    if not content["kopf"]["titel"]:
        return RedirectResponse("/datenblatt?error=Titel+eingeben", status_code=303)
    sheet = Datasheet(owner_id=user.id, title=ds.title_of(content), content=content)
    db.add(sheet)
    db.flush()
    audit(db, user, "datenblatt_angelegt", "datasheet", sheet.id, {"titel": sheet.title}, client_ip(request))
    return RedirectResponse(f"/datenblatt/{sheet.id}", status_code=303)


@router.get("/datenblatt/{sheet_id}")
def editor(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    c = ds.normalized(sheet.content)
    html, count = _pages_html(sheet, c)
    return render(request, "datasheet_editor.html", {
        "portal": True, "wide": True, "sheet": sheet, "c": c, "pages_html": html, "page_count": count,
        "colors": ds.COLORS, "blocks": ds.BLOCKS, "suggestions": ds.PROPERTY_SUGGESTIONS, "footer": ds.FOOTER,
        "heights": ds.IMAGE_HEIGHTS, "row_images": ds.ROW_IMAGES, "image_pos": ds.GROUP_IMAGE_POS,
        "max_columns": ds.MAX_COLUMNS, "new_table": ds.new_table(), "new_accessories": ds.new_table(zubehoer=True),
        "new_image": ds.new_image_block(),
    })


@router.get("/datenblatt/{sheet_id}/schritt/{step}")
def old_step_link(sheet_id: int):
    """Frühere Schritt-Links führen in den Editor."""
    return RedirectResponse(f"/datenblatt/{sheet_id}", status_code=303)


@router.post("/datenblatt/{sheet_id}/inhalt", dependencies=[Depends(check_csrf)])
async def save(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
               settings: Settings = Depends(get_settings)):
    """Automatisches Speichern aus dem Editor; Antwort enthält die neu berechneten Seiten für die Live-Vorschau."""
    sheet = get_visible(db, Datasheet, sheet_id, user)
    data = await _json(request)
    content = ds.sanitize(data.get("inhalt"), ds.image_names(settings, sheet.id))
    sheet.content = copy.deepcopy(content)
    sheet.title = ds.title_of(content)
    sheet.updated_at = utcnow()
    db.flush()
    ds.remove_unused_images(settings, sheet.id, content, grace=ds.UNUSED_IMAGE_GRACE_SECONDS)
    html, count = _pages_html(sheet, content)
    return {"ok": True, "titel": sheet.title, "html": html, "seiten": count,
            "gespeichert": sheet.updated_at.strftime("%H:%M:%S")}


@router.post("/datenblatt/{sheet_id}/bilder", dependencies=[Depends(check_csrf)])
async def upload_image(request: Request, sheet_id: int, db: Session = Depends(get_db),
                       user: User = Depends(current_user), settings: Settings = Depends(get_settings)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    form = await request.form()
    upload = form.get("datei")
    if not ds.is_upload(upload):
        return JSONResponse({"detail": "Keine Datei"}, status_code=400)
    try:
        name = await ds.save_image(settings, sheet.id, upload)
    except ds.ImageError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return {"name": name, "url": f"/datenblatt/{sheet.id}/bild/{name}"}


@router.post("/datenblatt/{sheet_id}/einfuegen", dependencies=[Depends(check_csrf)])
async def paste_rows(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Aus Excel kopierte Zeilen in Tabellenzeilen umwandeln (Farbe aus der Beschreibung)."""
    get_visible(db, Datasheet, sheet_id, user)
    data = await _json(request)
    columns = data.get("spalten") if isinstance(data.get("spalten"), int) else 0
    return {"zeilen": ds.parse_paste(str(data.get("text") or "")[:100_000], max(0, min(columns, ds.MAX_COLUMNS)))}


@router.get("/datenblatt/{sheet_id}/vorschau")
def preview(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    content = ds.normalized(sheet.content)
    return render(request, "datasheet_print.html", {
        "sheet": sheet, "c": content, "pages": ds.paginate(content), "footer": ds.FOOTER,
    })


@router.get("/datenblatt/{sheet_id}/bild/{name}")
def image(sheet_id: int, name: str, db: Session = Depends(get_db), user: User = Depends(current_user),
          settings: Settings = Depends(get_settings)):
    get_visible(db, Datasheet, sheet_id, user)
    path = ds.image_path(settings, sheet_id, name)
    if path is None:
        raise HTTPException(404, "Bild nicht gefunden")
    # Dateiname ist zufällig und ändert sich bei jedem neuen Bild, daher darf der Browser zwischenspeichern
    return FileResponse(path, media_type=ds.MEDIA_TYPES[path.suffix[1:]],
                        headers={"Cache-Control": "private, max-age=86400"})


@router.post("/datenblatt/{sheet_id}/kopieren", dependencies=[Depends(check_csrf)])
def duplicate(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
              settings: Settings = Depends(get_settings)):
    src = get_visible(db, Datasheet, sheet_id, user)
    copy_ = Datasheet(owner_id=user.id, title=f"{src.title} (Kopie)", content=copy.deepcopy(src.content))
    db.add(copy_)
    db.flush()
    ds.copy_images(settings, src.id, copy_.id)
    audit(db, user, "datenblatt_kopiert", "datasheet", copy_.id, {"von": src.id, "titel": src.title},
          client_ip(request))
    return RedirectResponse(f"/datenblatt/{copy_.id}", status_code=303)


@router.get("/datenblatt/{sheet_id}/loeschen")
def confirm_delete(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    return render(request, "confirm_delete.html", {
        "portal": True, "title": "Datenblatt löschen", "name": sheet.title, "action": f"/datenblatt/{sheet.id}/loeschen",
        "back": "/datenblatt", "impact": ["alle Texte, Tabellen und hochgeladenen Bilder dieses Datenblatts"]})


@router.post("/datenblatt/{sheet_id}/loeschen", dependencies=[Depends(check_csrf)])
async def delete(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
                 settings: Settings = Depends(get_settings)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    if (await request.form()).get("bestaetigt") != "ja":
        return RedirectResponse(f"/datenblatt/{sheet.id}/loeschen", status_code=303)
    audit(db, user, "datenblatt_geloescht", "datasheet", sheet.id, {"titel": sheet.title}, client_ip(request))
    db.delete(sheet)
    db.flush()
    ds.delete_images(settings, sheet_id)
    return RedirectResponse("/datenblatt", status_code=303)
