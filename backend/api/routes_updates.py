"""Jahresabgleich: unsere EK/VK-Liste (Vorjahr) mit der neuen Herstellerliste -> neue EK/VK-Liste."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.api.routes_lists import page_info
from backend.comparison.update import (
    REASON_LABELS, STATUS_LABELS, STATUSES, accept, bulk_accept, choose_candidate, manufacturer_settings,
    refresh_summary, run_update,
)
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.excel.export import export_price_update
from backend.excel.numbers import parse_amount
from backend.api.routes_compare import list_manufacturer
from backend.models.entities import Manufacturer, PriceList, PriceUpdate, PriceUpdateItem, Rule, User
from backend.services.audit import audit
from backend.services.manufacturers import code_map, search_conditions
from backend.services.rules import current_version

router = APIRouter()
BASIS_TYPES = ("EK", "UVP")


def _imported(db: Session):
    return db.scalars(select(PriceList).where(PriceList.status == "IMPORTIERT").order_by(PriceList.id.desc())).all()


@router.get("/aktualisierungen")
def updates(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return _list_page(request, db, None)


@router.post("/aktualisierungen", dependencies=[Depends(check_csrf)])
async def create_update(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()

    def as_int(key):
        v = str(form.get(key) or "")
        return int(v) if v.isdigit() else None

    errors = []
    base = db.get(PriceList, as_int("base_id")) if as_int("base_id") else None
    source = db.get(PriceList, as_int("source_id")) if as_int("source_id") else None
    mfr = None
    if not base or not source or base.status != "IMPORTIERT" or source.status != "IMPORTIERT":
        errors.append("Unsere Liste und Herstellerliste wählen")
    elif base.id == source.id:
        errors.append("Unsere Liste und Herstellerliste müssen verschieden sein")
    else:
        if base.kind == "HERSTELLER":
            errors.append(f"„{base.name}“ ist als Herstellerliste importiert, nicht als unsere Liste")
        if source.kind == "UNSERE":
            errors.append(f"„{source.name}“ ist als unsere Liste importiert, nicht als Herstellerliste")
        mb, ms = list_manufacturer(db, base), list_manufacturer(db, source)
        if mb and ms and mb != ms:
            errors.append("Unsere Liste und Herstellerliste gehören zu verschiedenen Herstellern")
        mfr = db.get(Manufacturer, ms or mb) if (ms or mb) else None
    settings = manufacturer_settings(mfr)
    price_type = str(form.get("price_type") or settings["basis"])
    if price_type not in BASIS_TYPES:
        errors.append("Herstellerliste enthält: EK oder UVP")
    elif price_type == "UVP" and settings["discount"] is None:
        errors.append("Händlerrabatt beim Hersteller hinterlegen (EK = UVP - Händlerrabatt)")
    qty = parse_amount(str(form.get("quantity") or "1"), ",")
    if not qty.ok or qty.value <= 0:
        errors.append("Menge muss größer 0 sein")
    rule_version_id = None
    rule = db.get(Rule, as_int("rule_id")) if as_int("rule_id") else None
    if rule is None or rule.deleted:
        errors.append("Kalkulationsregel für den VK wählen")
    else:
        rule_version_id = current_version(db, rule).id
    if errors:
        return _list_page(request, db, "; ".join(errors), 400)
    upd = PriceUpdate(base_price_list_id=base.id, source_price_list_id=source.id, price_type=price_type,
                      rule_version_id=rule_version_id, quantity=qty.value, created_by=user.id,
                      dealer_discount=settings["discount"] if price_type == "UVP" else None,
                      review_threshold=settings["threshold"])
    db.add(upd)
    db.flush()
    summary = run_update(db, upd)
    audit(db, user, "jahresabgleich", "price_update", upd.id,
          {"basis": base.id, "hersteller": source.id, "typ": price_type, "rabatt": str(upd.dealer_discount),
           "schwelle": str(upd.review_threshold), "zusammenfassung": summary}, client_ip(request))
    return RedirectResponse(f"/aktualisierungen/{upd.id}", status_code=303)


def _list_page(request, db, error, status_code=200):
    items = db.scalars(select(PriceUpdate).order_by(PriceUpdate.id.desc())).all()
    rules = db.scalars(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name)).all()
    return render(request, "updates.html", {"updates": items, "lists": _imported(db), "rules": rules,
                                            "labels": STATUS_LABELS, "error": error}, status_code=status_code)


def _get(db: Session, upd_id: int) -> PriceUpdate:
    upd = db.get(PriceUpdate, upd_id)
    if upd is None:
        raise HTTPException(404, "Abgleich nicht gefunden")
    return upd


FILTERS = ("offen",) + STATUSES


@router.get("/aktualisierungen/{upd_id}")
def update_detail(request: Request, upd_id: int, status: str | None = None, grund: str | None = None,
                  q: str | None = None, page: int = 1, meldung: str | None = None,
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                  _user: User = Depends(current_user)):
    upd = _get(db, upd_id)
    stmt = select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd_id)
    if status == "offen":
        stmt = stmt.where(PriceUpdateItem.needs_review.is_(True), PriceUpdateItem.reviewed_at.is_(None))
    elif status in STATUSES:
        stmt = stmt.where(PriceUpdateItem.status == status)
    if grund in REASON_LABELS:
        stmt = stmt.where(func.json_extract(PriceUpdateItem.reasons, "$").like(f'%"{grund}"%'))
    if q:
        q = q.strip()[:100]
        stmt = stmt.where(or_(PriceUpdateItem.article_number.ilike(f"%{q}%"),
                              PriceUpdateItem.description.ilike(f"%{q}%"),
                              *search_conditions(db, q, PriceUpdateItem.article_number,
                                                 PriceUpdateItem.manufacturer_id)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    info = page_info(total, page, settings.page_size)
    rows = db.scalars(stmt.order_by(PriceUpdateItem.id).offset(info["offset"]).limit(settings.page_size)).all()
    reviewers = {u.id: u.username for u in db.scalars(select(User))}
    return render(request, "update.html", {
        "upd": upd, "rows": rows, "info": info, "status": status if status in FILTERS else "",
        "grund": grund if grund in REASON_LABELS else "", "q": q or "", "meldung": meldung,
        "statuses": STATUSES, "labels": STATUS_LABELS, "reasons": REASON_LABELS, "codes": code_map(db),
        "step": 6, "reviewers": reviewers,
        "rule": db.get(Rule, upd.rule_version.rule_id) if upd.rule_version else None,
    })


def _back(upd_id: int, form, msg: str | None = None) -> RedirectResponse:
    params = {k: str(form.get(k)) for k in ("status", "grund", "q", "page") if form.get(k)}
    if msg:
        params["meldung"] = msg
    return RedirectResponse(f"/aktualisierungen/{upd_id}?{urlencode(params)}", status_code=303)


@router.post("/aktualisierungen/{upd_id}/positionen/{item_id}", dependencies=[Depends(check_csrf)])
async def review_item(request: Request, upd_id: int, item_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    upd = _get(db, upd_id)
    item = db.get(PriceUpdateItem, item_id)
    if item is None or item.update_id != upd.id:
        raise HTTPException(404, "Position nicht gefunden")
    form = await request.form()
    action = str(form.get("action") or "")
    before = {"status": item.status, "ek": str(item.final_ek), "vk": str(item.final_vk),
              "entscheidung": item.decision}
    try:
        if action == "bestaetigen":
            if item.status == "NICHT_EINDEUTIG":
                raise ValueError("Zuordnung zuerst auswählen (Kandidat oder „kein Treffer“)")
            raw = str(form.get("manual_vk") or "").strip()
            manual = None
            if raw:
                if item.status == "FEHLER":
                    raise ValueError("Bei Fehlern bleibt der alte Preis, ein VK von Hand ist hier nicht möglich")
                parsed = parse_amount(raw, ",")
                if not parsed.ok:
                    raise ValueError(f"VK „{raw[:30]}“ ist keine gültige Zahl")
                manual = parsed.value
            accept(db, item, user.id, manual)
        elif action == "zuordnen":
            raw = str(form.get("new_id") or "")
            if raw != "kein" and not raw.isdigit():
                raise ValueError("Kandidat wählen")
            choose_candidate(db, upd, item, None if raw == "kein" else int(raw), user.id)
        elif action == "zuruecknehmen":
            item.reviewed_by = item.reviewed_at = None
            if item.decision == "MANUELL":
                item.final_vk = item.calculated_amount if item.calculated_amount is not None else item.vk_old
                item.decision = "NEU" if item.calculated_amount is not None else "ALT"
        else:
            raise ValueError("Unbekannte Aktion")
    except ValueError as e:
        db.rollback()
        return _back(upd_id, form, str(e))
    db.flush()
    refresh_summary(db, upd)
    audit(db, user, "abgleich_position_" + action, "price_update_item", item.id,
          {"abgleich": upd.id, "artikel": item.article_number, "vorher": before,
           "nachher": {"status": item.status, "ek": str(item.final_ek), "vk": str(item.final_vk),
                       "entscheidung": item.decision}}, client_ip(request))
    return _back(upd_id, form)


@router.post("/aktualisierungen/{upd_id}/alle-bestaetigen", dependencies=[Depends(check_csrf)])
async def review_bulk(request: Request, upd_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    upd = _get(db, upd_id)
    form = await request.form()
    if form.get("bestaetigt") != "ja":
        return _back(upd_id, form, "Bitte das Häkchen zur Bestätigung setzen")
    status = str(form.get("status") or "")
    grund = str(form.get("grund") or "")
    n = bulk_accept(db, upd, user.id, status if status in STATUSES else None,
                    grund if grund in REASON_LABELS else None)
    db.flush()
    refresh_summary(db, upd)
    audit(db, user, "abgleich_sammelbestaetigung", "price_update", upd.id,
          {"status": status, "grund": grund, "anzahl": n}, client_ip(request))
    return _back(upd_id, form, f"{n} Positionen bestätigt")


@router.get("/aktualisierungen/{upd_id}/export")
def export(request: Request, upd_id: int, entwurf: int = 0, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    upd = _get(db, upd_id)
    refresh_summary(db, upd)
    open_ = (upd.summary or {}).get("offen", 0)
    if not entwurf and open_:
        raise HTTPException(409, f"Endgültiger Export gesperrt: {open_} Positionen sind noch nicht geprüft. "
                                 "Bitte prüfen oder den Entwurf exportieren.")
    data = export_price_update(db, upd, draft=bool(entwurf))
    audit(db, user, "export_entwurf" if entwurf else "export", "price_update", upd_id,
          {"offen": open_}, client_ip(request))
    prefix = "ENTWURF_" if entwurf else ""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{prefix}Neue_Preisliste_{upd.base_list.name}_{upd_id}")[:80]
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
