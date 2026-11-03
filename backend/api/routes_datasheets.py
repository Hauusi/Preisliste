"""Modul „Datenblatt erstellen“: Liste, Editor mit Live-Vorschau, Druck/PDF, Bilder."""

from __future__ import annotations

import copy
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user, require_admin
from backend.api.render import render
from backend.api.templating import templates
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import Datasheet, DatasheetExample, DatasheetTerm, Job, Manufacturer, User, utcnow
from backend.services import datasheet_import as dsi
from backend.services import datasheet_terms
from backend.services import datasheets as ds
from backend.services.access import can_see, get_visible, is_admin, visible
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


def _readable(db: Session, sheet_id: int, user: User) -> Datasheet:
    """Eigene (Admin: alle) oder freigegebene Datenblätter – zum Ansehen, Drucken, Kopieren."""
    sheet = db.get(Datasheet, sheet_id)
    if sheet is not None and sheet.released_at and not sheet.is_template:
        return sheet
    return get_visible(db, Datasheet, sheet_id, user)


def _matches(sheet: Datasheet, query: str) -> bool:
    """Suche in Titel und Artikelnummern (ohne Leerzeichen/Bindestriche, Groß-/Kleinschreibung egal)."""
    def norm(text):
        return re.sub(r"[\s\-./]", "", str(text or "")).lower()

    q = norm(query)
    if q in norm(sheet.title):
        return True
    return any(q in norm(r.get("artnr")) for t in ds.tables(sheet.content) for r in t["zeilen"])


@router.get("/datenblatt")
def overview(request: Request, error: str | None = None, q: str = "", db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    sheets = db.scalars(visible(select(Datasheet).where(Datasheet.is_template.is_(False))  # Vorlagen: eigene Seite
                                .order_by(Datasheet.updated_at.desc()), Datasheet, user)).all()
    released = db.scalars(select(Datasheet).where(Datasheet.is_template.is_(False), Datasheet.released_at.is_not(None))
                          .order_by(Datasheet.updated_at.desc())).all()
    q = q.strip()[:60]
    if q:
        released = [s_ for s_ in released if _matches(s_, q)]
    names = {u.id: u.username for u in db.scalars(select(User))}
    owners = names if is_admin(user) else {}
    manufacturers = db.scalars(visible(select(Manufacturer).order_by(Manufacturer.name), Manufacturer, user)).all()
    return render(request, "datasheets.html", {"portal": True, "sheets": sheets, "owners": owners, "error": error,
                                               "manufacturers": manufacturers, "released": released, "names": names,
                                               "q": q})


@router.post("/datenblatt/{sheet_id}/freigeben", dependencies=[Depends(check_csrf)])
async def release(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Fertiges Datenblatt für alle Benutzer freigeben (gemeinsame Liste) bzw. Freigabe zurücknehmen."""
    sheet = get_visible(db, Datasheet, sheet_id, user)  # nur Besitzer oder Admin
    form = await request.form()
    on = str(form.get("aktiv") or "") == "1"
    sheet.released_at, sheet.released_by = (utcnow(), user.id) if on else (None, None)
    audit(db, user, "datenblatt_freigegeben" if on else "datenblatt_freigabe_zurueck", "datasheet", sheet.id,
          {"titel": sheet.title}, client_ip(request))
    back = str(form.get("zurueck") or "")
    return RedirectResponse(back if back in ("/datenblatt", f"/datenblatt/{sheet.id}") else "/datenblatt",
                            status_code=303)


@router.get("/datenblatt/vorlagen")
def templates_page(request: Request, error: str | None = None, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    """Design-Vorlagen (nur Admin): unsere fertigen Datenblätter als Original-PDF. Das Tool liest daraus ab, wo
    Bilder hingehören und wie Texte geschrieben sind, und richtet „Aus Hersteller-Datenblatt erstellen“ danach aus."""
    from backend.services import datasheet_examples as dse

    examples = db.scalars(select(DatasheetExample).order_by(DatasheetExample.created_at.desc())).all()
    kinds = sorted({k for e in examples for k in dse.kinds_of(e.kind)})
    data = [{"art": e.kind, "profil": e.profile} for e in examples]
    rules = {k: dse.summary(dse.design(dse.choose(data, k)[0])) for k in kinds}
    general = dse.summary(dse.design(dse.choose(data, None)[0]))
    old = db.scalars(select(Datasheet).where(Datasheet.is_template.is_(True))).all()  # frühere, nachgebaute Vorlagen
    return render(request, "datasheet_templates.html", {
        "portal": True, "examples": examples, "rules": rules, "general": general, "old": old, "error": error,
        "kinds": list(dsi.PRODUCT_TYPES)})


@router.post("/datenblatt/vorlagen", dependencies=[Depends(check_csrf)])
async def templates_upload(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin),
                           settings: Settings = Depends(get_settings)):
    """Eines oder mehrere unserer Datenblätter (PDF) als Vorlage speichern; Auswertung im Hintergrund."""
    from urllib.parse import quote

    from backend.jobs.runner import enqueue
    from backend.services import datasheet_examples as dse

    form = await request.form()
    files = [f for f in form.getlist("dateien") if ds.is_upload(f)]
    if not files:
        return RedirectResponse("/datenblatt/vorlagen?error=" + quote("Bitte mindestens ein PDF auswählen"),
                                status_code=303)
    kind = ", ".join(k.strip() for k in str(form.get("art") or "").split(",") if k.strip())[:60] or None
    ids = []
    for f in files[:30]:
        data = await f.read(dsi.MAX_PDF_BYTES + 1)
        try:
            dsi.check_pdf(data)
        except dsi.PdfError as exc:
            return RedirectResponse("/datenblatt/vorlagen?error=" + quote(f"{f.filename}: {exc}"), status_code=303)
        ex = DatasheetExample(filename=dse.clean_filename(str(f.filename or "vorlage.pdf")), kind=kind, profile={},
                              created_by=admin.id)
        db.add(ex)
        db.flush()
        path = dse.pdf_path(settings, ex.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        ids.append(ex.id)
    job = enqueue(db, "DATENBLATT_VORLAGEN", {"ids": ids}, admin)
    audit(db, admin, "datenblatt_vorlagen_hochgeladen", "datasheet_example", None, {"anzahl": len(ids)},
          client_ip(request))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/datenblatt/vorlagen/{example_id}/pdf")
def template_pdf(example_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin),
                 settings: Settings = Depends(get_settings)):
    from backend.services import datasheet_examples as dse

    ex = db.get(DatasheetExample, example_id)
    path = dse.pdf_path(settings, example_id)
    if ex is None or not path.is_file():
        raise HTTPException(404, "Vorlage nicht gefunden")
    return FileResponse(path, media_type="application/pdf", filename=ex.filename, content_disposition_type="inline")


@router.post("/datenblatt/vorlagen/{example_id}/art", dependencies=[Depends(check_csrf)])
async def template_kind(request: Request, example_id: int, db: Session = Depends(get_db),
                        admin: User = Depends(require_admin)):
    ex = db.get(DatasheetExample, example_id)
    if ex is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    form = await request.form()
    ex.kind = ", ".join(k.strip() for k in str(form.get("art") or "").split(",") if k.strip())[:60] or None
    audit(db, admin, "datenblatt_vorlage_art", "datasheet_example", ex.id, {"art": ex.kind}, client_ip(request))
    return RedirectResponse("/datenblatt/vorlagen", status_code=303)


@router.get("/datenblatt/vorlagen/{example_id}/loeschen")
def template_confirm_delete(request: Request, example_id: int, db: Session = Depends(get_db),
                            _admin: User = Depends(require_admin)):
    ex = db.get(DatasheetExample, example_id)
    if ex is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    return render(request, "confirm_delete.html", {
        "portal": True, "title": "Design-Vorlage löschen", "name": ex.title or ex.filename,
        "action": f"/datenblatt/vorlagen/{ex.id}/loeschen", "back": "/datenblatt/vorlagen",
        "impact": ["das gespeicherte PDF und was daraus abgelesen wurde (bestehende Datenblätter bleiben unverändert)"]})


@router.post("/datenblatt/vorlagen/{example_id}/loeschen", dependencies=[Depends(check_csrf)])
async def template_delete(request: Request, example_id: int, db: Session = Depends(get_db),
                          admin: User = Depends(require_admin), settings: Settings = Depends(get_settings)):
    from backend.services import datasheet_examples as dse

    ex = db.get(DatasheetExample, example_id)
    if ex is None:
        raise HTTPException(404, "Vorlage nicht gefunden")
    if (await request.form()).get("bestaetigt") != "ja":
        return RedirectResponse(f"/datenblatt/vorlagen/{ex.id}/loeschen", status_code=303)
    audit(db, admin, "datenblatt_vorlage_geloescht", "datasheet_example", ex.id, {"datei": ex.filename},
          client_ip(request))
    db.delete(ex)
    dse.pdf_path(settings, example_id).unlink(missing_ok=True)
    return RedirectResponse("/datenblatt/vorlagen", status_code=303)


@router.post("/datenblatt/{sheet_id}/vorlage", dependencies=[Depends(check_csrf)])
async def set_template(request: Request, sheet_id: int, db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    """Frühere, nachgebaute Vorlage zurück in die normale Liste (aktiv=1 markiert wieder; nur noch Altbestand)."""
    sheet = get_visible(db, Datasheet, sheet_id, admin)
    form = await request.form()
    active = str(form.get("aktiv") or "") == "1"
    kinds = ", ".join(k.strip() for k in str(form.get("art") or "").split(",") if k.strip())[:60]
    if active and not kinds:
        title = ds.normalized(sheet.content)["kopf"]["titel"]
        kinds = dsi.product_type(title, "") or ""
    sheet.is_template, sheet.template_kind = active, (kinds or None) if active else None
    audit(db, admin, "datenblatt_vorlage", "datasheet", sheet.id, {"vorlage": active, "art": sheet.template_kind},
          client_ip(request))
    return RedirectResponse("/datenblatt/vorlagen", status_code=303)


# ---------- Wörterbuch für den Import (nur Admin) ----------

@router.get("/datenblatt/woerterbuch")
def terms_page(request: Request, hersteller: str | None = None, art: str | None = None, begriff: str | None = None,
               error: str | None = None, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Wörterbuch: Herstellerbegriff -> B&B-Begriff, für alle oder einen Hersteller. Mit art/begriff (Link aus dem
    Prüfbericht) ist das Formular vorausgefüllt."""
    stmt = select(DatasheetTerm).order_by(DatasheetTerm.manufacturer, DatasheetTerm.kind, DatasheetTerm.source)
    if hersteller is not None and hersteller != "*":
        stmt = stmt.where(DatasheetTerm.manufacturer == hersteller)
    return render(request, "datasheet_terms.html", {
        "portal": True, "terms": db.scalars(stmt).all(), "kinds": datasheet_terms.KINDS, "hints": datasheet_terms.HINTS,
        "manufacturers": datasheet_terms.manufacturer_names(db), "filter": hersteller if hersteller is not None else "*",
        "prefill": {"art": art if art in datasheet_terms.KINDS else "MERKMAL", "begriff": (begriff or "")[:120],
                    "hersteller": hersteller if hersteller not in (None, "*") else ""},
        "builtin": datasheet_terms.builtin_rules(), "error": error})


def _terms_redirect(hersteller: str, error: str | None = None) -> RedirectResponse:
    from urllib.parse import urlencode

    query = {"hersteller": hersteller or ""}
    if error:
        query["error"] = error
    return RedirectResponse("/datenblatt/woerterbuch?" + urlencode(query), status_code=303)


@router.post("/datenblatt/woerterbuch", dependencies=[Depends(check_csrf)])
async def terms_add(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    form = await request.form()
    kind = str(form.get("art") or "")
    source = dsi.term_key(str(form.get("begriff") or ""))[:120]
    target = " ".join(str(form.get("ziel") or "").split())[:200]
    manufacturer = str(form.get("hersteller") or "").strip()[:200]
    if kind not in datasheet_terms.KINDS or not source or not target:
        return _terms_redirect(manufacturer, "Art, Herstellerbegriff und unser Begriff ausfüllen.")
    row = db.scalar(select(DatasheetTerm).where(DatasheetTerm.kind == kind, DatasheetTerm.source == source,
                                                DatasheetTerm.manufacturer == manufacturer))
    if row:
        row.target = target  # gleicher Begriff nochmal: überschreiben
    else:
        row = DatasheetTerm(kind=kind, source=source, target=target, manufacturer=manufacturer, created_by=admin.id)
        db.add(row)
    db.flush()
    audit(db, admin, "woerterbuch_eintrag", "datasheet_term", row.id,
          {"art": kind, "begriff": source, "ziel": target, "hersteller": manufacturer}, client_ip(request))
    return _terms_redirect(manufacturer)


@router.post("/datenblatt/woerterbuch/{term_id}/aendern", dependencies=[Depends(check_csrf)])
async def terms_edit(request: Request, term_id: int, db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    row = db.get(DatasheetTerm, term_id)
    if row is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    form = await request.form()
    target = " ".join(str(form.get("ziel") or "").split())[:200]
    if target:
        row.target = target
        audit(db, admin, "woerterbuch_geaendert", "datasheet_term", row.id, {"ziel": target}, client_ip(request))
    return _terms_redirect(str(form.get("filter") or ""))


@router.post("/datenblatt/woerterbuch/{term_id}/loeschen", dependencies=[Depends(check_csrf)])
async def terms_delete(request: Request, term_id: int, db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    row = db.get(DatasheetTerm, term_id)
    if row is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    form = await request.form()
    audit(db, admin, "woerterbuch_geloescht", "datasheet_term", row.id,
          {"art": row.kind, "begriff": row.source, "hersteller": row.manufacturer}, client_ip(request))
    db.delete(row)
    return _terms_redirect(str(form.get("filter") or ""))


@router.post("/datenblatt/aus-pdf", dependencies=[Depends(check_csrf)])
async def create_from_pdf(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                          settings: Settings = Depends(get_settings)):
    """Hersteller-Datenblatt (PDF) hochladen: leeres Datenblatt anlegen, Baukasten im Hintergrund füllen."""
    from urllib.parse import quote

    from backend.jobs.runner import enqueue

    form = await request.form()
    back = "/datenblatt"
    upload = form.get("datei")
    if not ds.is_upload(upload):
        return RedirectResponse(back + "?error=" + quote("Bitte ein PDF auswählen"), status_code=303)
    data = await upload.read(dsi.MAX_PDF_BYTES + 1)
    try:
        dsi.check_pdf(data)
    except dsi.PdfError as exc:
        return RedirectResponse(back + "?error=" + quote(str(exc)), status_code=303)
    mid = str(form.get("hersteller") or "")
    manufacturer = get_visible(db, Manufacturer, int(mid), user) if mid.isdigit() else None
    content = ds.empty_content()
    content["kopf"]["titel"] = "Wird aus dem Herstellerblatt erstellt"
    sheet = Datasheet(owner_id=user.id, title=content["kopf"]["titel"], content=content)
    db.add(sheet)
    db.flush()
    dsi.save_pdf(settings, sheet.id, data)
    job = enqueue(db, "DATENBLATT_IMPORT", {"datasheet_id": sheet.id, "manufacturer_id": manufacturer.id if manufacturer else None,
                                           "datei": str(upload.filename)[:200]}, user)
    audit(db, user, "datenblatt_aus_pdf", "datasheet", sheet.id, {"datei": str(upload.filename)[:200]}, client_ip(request))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


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
def editor(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
           settings: Settings = Depends(get_settings)):
    sheet = _readable(db, sheet_id, user)
    if not can_see(sheet, user):  # freigegebenes Blatt eines anderen: nur ansehen
        return RedirectResponse(f"/datenblatt/{sheet.id}/vorschau", status_code=303)
    c = ds.normalized(sheet.content)
    html, count = _pages_html(sheet, c)
    imported = None  # Bericht nach „aus Herstellerblatt erstellen“
    job_id = request.query_params.get("import")
    if job_id and job_id.isdigit():
        job = db.get(Job, int(job_id))
        if job and job.type == "DATENBLATT_IMPORT" and (job.result or {}).get("datasheet_id") == sheet.id:
            imported = job.result
    return render(request, "datasheet_editor.html", {
        "portal": True, "wide": True, "sheet": sheet, "c": c, "pages_html": html, "page_count": count,
        "colors": ds.COLORS, "color_choices": ds.color_choices, "blocks": ds.BLOCKS, "suggestions": ds.PROPERTY_SUGGESTIONS, "footer": ds.FOOTER,
        "heights": ds.IMAGE_HEIGHTS, "row_images": ds.ROW_IMAGES, "image_pos": ds.GROUP_IMAGE_POS,
        "max_columns": ds.MAX_COLUMNS, "new_table": ds.new_table(), "new_accessories": ds.new_table(zubehoer=True),
        "new_image": ds.new_image_block(), "twins": ds.twin_names(settings, sheet.id), "imported": imported,
        "splits": ds.LEAD_SPLITS,
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
        # Anwendungsbilder bleiben wie geliefert, alle anderen werden als PNG freigestellt
        name = await ds.save_image(settings, sheet.id, upload, product=form.get("art") != "anwendung")
    except ds.ImageError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return {"name": name, "url": f"/datenblatt/{sheet.id}/bild/{name}",
            "zweitfassung": ds.other_version(settings, sheet.id, name)}


@router.post("/datenblatt/{sheet_id}/einfuegen", dependencies=[Depends(check_csrf)])
async def paste_rows(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Aus Excel kopierte Zeilen in Tabellenzeilen umwandeln (Farbe aus der Beschreibung)."""
    get_visible(db, Datasheet, sheet_id, user)
    data = await _json(request)
    columns = data.get("spalten") if isinstance(data.get("spalten"), int) else 0
    return {"zeilen": ds.parse_paste(str(data.get("text") or "")[:100_000], max(0, min(columns, ds.MAX_COLUMNS)))}


@router.get("/datenblatt/{sheet_id}/vorschau")
def preview(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = _readable(db, sheet_id, user)
    content = ds.normalized(sheet.content)
    return render(request, "datasheet_print.html", {
        "sheet": sheet, "c": content, "pages": ds.paginate(content), "footer": ds.FOOTER,
        "can_edit": can_see(sheet, user),
    })


@router.post("/datenblatt/{sheet_id}/bild/{name}/hintergrund", dependencies=[Depends(check_csrf)])
def toggle_background(sheet_id: int, name: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                      settings: Settings = Depends(get_settings)):
    """Zwischen freigestelltem Bild und Original mit Hintergrund wechseln."""
    sheet = get_visible(db, Datasheet, sheet_id, user)
    other = ds.other_version(settings, sheet.id, name)
    if other is None:
        return JSONResponse({"detail": "Für dieses Bild gibt es keine zweite Fassung (Hintergrund wurde nicht entfernt)"},
                            status_code=404)
    return {"name": other, "url": f"/datenblatt/{sheet.id}/bild/{other}", "hintergrund": "-o." in other}


@router.get("/datenblatt/{sheet_id}/bild/{name}")
def image(sheet_id: int, name: str, db: Session = Depends(get_db), user: User = Depends(current_user),
          settings: Settings = Depends(get_settings)):
    _readable(db, sheet_id, user)
    path = ds.image_path(settings, sheet_id, name)
    if path is None:
        raise HTTPException(404, "Bild nicht gefunden")
    # Dateiname ist zufällig und ändert sich bei jedem neuen Bild, daher darf der Browser zwischenspeichern
    return FileResponse(path, media_type=ds.MEDIA_TYPES[path.suffix[1:]],
                        headers={"Cache-Control": "private, max-age=86400"})


@router.post("/datenblatt/{sheet_id}/kopieren", dependencies=[Depends(check_csrf)])
def duplicate(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
              settings: Settings = Depends(get_settings)):
    src = _readable(db, sheet_id, user)
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
        "portal": True, "title": "Vorlage löschen" if sheet.is_template else "Datenblatt löschen", "name": sheet.title,
        "action": f"/datenblatt/{sheet.id}/loeschen",
        "back": "/datenblatt/vorlagen" if sheet.is_template else "/datenblatt", "impact": ["alle Texte, Tabellen und hochgeladenen Bilder dieses Datenblatts"]})


@router.post("/datenblatt/{sheet_id}/loeschen", dependencies=[Depends(check_csrf)])
async def delete(request: Request, sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
                 settings: Settings = Depends(get_settings)):
    sheet = get_visible(db, Datasheet, sheet_id, user)
    if (await request.form()).get("bestaetigt") != "ja":
        return RedirectResponse(f"/datenblatt/{sheet.id}/loeschen", status_code=303)
    was_template = sheet.is_template
    audit(db, user, "datenblatt_geloescht", "datasheet", sheet.id, {"titel": sheet.title}, client_ip(request))
    db.delete(sheet)
    db.flush()
    ds.delete_images(settings, sheet_id)
    return RedirectResponse("/datenblatt/vorlagen" if was_template else "/datenblatt", status_code=303)
