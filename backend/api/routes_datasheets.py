"""Modul „Datenblatt erstellen“: Liste, Schritt-für-Schritt-Eingabe, Vorschau/Druck, Bilder."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import Datasheet, User, utcnow
from backend.services import datasheets as ds
from backend.services.access import get_visible, is_admin, visible
from backend.services.audit import audit

router = APIRouter()


def _step_page(request, sheet, step, content, errors=None, status_code=200):
    index = ds.STEP_KEYS.index(step)
    return render(request, "datasheet_step.html", {
        "portal": True, "sheet": sheet, "step": step, "step_label": dict(ds.STEPS)[step], "index": index,
        "steps": ds.STEPS, "done": {k: ds.step_done(content, k) for k in ds.STEP_KEYS}, "c": ds.normalized(content),
        "colors": ds.COLORS, "spare": ds.SPARE_ROWS, "max_badges": ds.MAX_BADGES, "max_columns": ds.MAX_COLUMNS,
        "slots": ds.IMAGE_SLOTS, "suggestions": ds.PROPERTY_SUGGESTIONS, "footer": ds.FOOTER, "errors": errors or [],
        "is_last": index == len(ds.STEPS) - 1,
    }, status_code=status_code)


@router.get("/datenblatt")
def overview(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheets = db.scalars(visible(select(Datasheet).order_by(Datasheet.updated_at.desc()), Datasheet, user)).all()
    owners = {u.id: u.username for u in db.scalars(select(User))} if is_admin(user) else {}
    return render(request, "datasheets.html", {"portal": True, "sheets": sheets, "owners": owners})


@router.get("/datenblatt/neu")
def new_form(request: Request, _user: User = Depends(current_user)):
    return _step_page(request, None, "kopf", ds.empty_content())


@router.post("/datenblatt/neu", dependencies=[Depends(check_csrf)])
async def create(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    content, _ = await ds.apply_step(ds.empty_content(), "kopf", form, None)
    if not content["kopf"]["titel"]:
        return _step_page(request, None, "kopf", content, ["Bitte einen Titel für die Kopfzeile eingeben"], 400)
    sheet = Datasheet(owner_id=user.id, title=ds.title_of(content), content=content)
    db.add(sheet)
    db.flush()
    audit(db, user, "datenblatt_angelegt", "datasheet", sheet.id, {"titel": sheet.title}, client_ip(request))
    return RedirectResponse(f"/datenblatt/{sheet.id}/schritt/{ds.STEP_KEYS[1]}", status_code=303)


@router.get("/datenblatt/{sheet_id}")
def open_sheet(sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_visible(db, Datasheet, sheet_id, user)
    return RedirectResponse(f"/datenblatt/{sheet_id}/schritt/kopf", status_code=303)


@router.get("/datenblatt/{sheet_id}/schritt/{step}")
def step_form(request: Request, sheet_id: int, step: str, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    if step not in ds.STEP_KEYS:
        raise HTTPException(404, "Schritt nicht gefunden")
    return _step_page(request, sheet, step, sheet.content)


@router.post("/datenblatt/{sheet_id}/schritt/{step}", dependencies=[Depends(check_csrf)])
async def step_save(request: Request, sheet_id: int, step: str, db: Session = Depends(get_db),
                    user: User = Depends(current_user), settings: Settings = Depends(get_settings)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    if step not in ds.STEP_KEYS:
        raise HTTPException(404, "Schritt nicht gefunden")
    form = await request.form()

    async def store(upload):
        return await ds.save_image(settings, sheet.id, upload)

    content, errors = await ds.apply_step(sheet.content, step, form, store)
    if step == "kopf" and not content["kopf"]["titel"]:
        errors.append("Bitte einen Titel für die Kopfzeile eingeben")
        content["kopf"]["titel"] = ds.normalized(sheet.content)["kopf"]["titel"]
    sheet.content = copy.deepcopy(content)
    sheet.title = ds.title_of(content)
    sheet.updated_at = utcnow()
    db.flush()
    ds.remove_unused_images(settings, sheet.id, content)
    if errors:
        return _step_page(request, sheet, step, content, errors, 400)

    action = form.get("aktion")
    index = ds.STEP_KEYS.index(step)
    if action == "zurueck" and index > 0:
        target = f"/datenblatt/{sheet.id}/schritt/{ds.STEP_KEYS[index - 1]}"
    elif action == "weiter" and index < len(ds.STEP_KEYS) - 1:
        target = f"/datenblatt/{sheet.id}/schritt/{ds.STEP_KEYS[index + 1]}"
    elif action in ("weiter", "fertig", "vorschau"):
        target = f"/datenblatt/{sheet.id}/vorschau"
    elif isinstance(action, str) and action.startswith("gehe:") and action[5:] in ds.STEP_KEYS:
        target = f"/datenblatt/{sheet.id}/schritt/{action[5:]}"
    else:  # speichern, Gruppe hinzufügen: auf dem Schritt bleiben
        target = f"/datenblatt/{sheet.id}/schritt/{step}" + ("#neu" if action == "gruppe" else "")
    return RedirectResponse(target, status_code=303)


@router.get("/datenblatt/{sheet_id}/vorschau")
def preview(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    content = ds.normalized(sheet.content)
    return render(request, "datasheet_print.html", {
        "sheet": sheet, "c": content, "pages": ds.paginate(content), "footer": ds.FOOTER, "props": ds.shown_properties(content),
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
    return RedirectResponse(f"/datenblatt/{copy_.id}/schritt/kopf", status_code=303)


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
