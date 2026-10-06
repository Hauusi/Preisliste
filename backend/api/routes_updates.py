"""Jahresabgleich: unsere EK/VK-Liste (Vorjahr) mit der neuen Herstellerliste -> neue EK/VK-Liste."""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.api.routes_lists import page_info
from backend.comparison.update import (
    REASON_LABELS, SCOPES, STATUS_LABELS, STATUSES, accept, adopt_as_current, bulk_accept, choose_candidate,
    decide_ai_hint, manufacturer_settings, refresh_summary, rule_for_factor, run_update, set_article_rule, snapshot_exceptions,
)
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.excel.export import export_price_update
from backend.excel.numbers import parse_amount
from backend.api.routes_compare import list_manufacturer
from backend.services.access import get_visible, visible, visible_or_none
from backend.services.updates import start_update
from backend.models.entities import Article, ArticlePrice, Manufacturer, PriceList, PriceUpdate, PriceUpdateItem, Rule, User
from backend.services.audit import audit
from backend.services.manufacturers import code_map, search_conditions
from backend.services.rules import current_version

router = APIRouter()
BASIS_TYPES = ("EK", "UVP")


def _imported(db: Session, user: User):
    return db.scalars(visible(select(PriceList).where(PriceList.status == "IMPORTIERT")
                              .order_by(PriceList.id.desc()), PriceList, user)).all()


@router.get("/aktualisierungen")
def updates(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _list_page(request, db, user, None)


@router.post("/aktualisierungen", dependencies=[Depends(check_csrf)])
async def create_update(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()

    def as_int(key):
        v = str(form.get(key) or "")
        return int(v) if v.isdigit() else None

    base = visible_or_none(db, PriceList, as_int("base_id"), user)
    source = visible_or_none(db, PriceList, as_int("source_id"), user)
    rule = visible_or_none(db, Rule, as_int("rule_id"), user)
    qty = parse_amount(str(form.get("quantity") or "1"), ",")
    upd, errors = start_update(db, base, source, rule, str(form.get("scope") or "VOLL"),
                               str(form.get("price_type") or "") or None, qty.value if qty.ok else None)
    if errors:
        return _list_page(request, db, user, "; ".join(errors), 400)
    summary, price_type, scope = upd.summary, upd.price_type, upd.scope
    audit(db, user, "jahresabgleich", "price_update", upd.id,
          {"basis": base.id, "hersteller": source.id, "typ": price_type, "rabatt": str(upd.dealer_discount),
           "schwelle": str(upd.review_threshold), "umfang": scope, "waehrung": upd.list_currency,
           "kurs": str(upd.exchange_rate), "ausnahmen": upd.exceptions, "zusammenfassung": summary}, client_ip(request))
    return RedirectResponse(f"/aktualisierungen/{upd.id}", status_code=303)


def _list_page(request, db, user, error, status_code=200):
    items = db.scalars(visible(select(PriceUpdate).order_by(PriceUpdate.id.desc()), PriceUpdate, user)).all()
    rules = db.scalars(visible(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name), Rule, user)).all()
    return render(request, "updates.html", {"updates": items, "lists": _imported(db, user), "rules": rules,
                                            "labels": STATUS_LABELS, "error": error}, status_code=status_code)


def _get(db: Session, upd_id: int, user: User) -> PriceUpdate:
    return get_visible(db, PriceUpdate, upd_id, user)


FILTERS = ("offen", "alle") + STATUSES


@router.get("/aktualisierungen/{upd_id}")
def update_detail(request: Request, upd_id: int, status: str | None = None, grund: str | None = None,
                  fertig: int = 0,
                  q: str | None = None, page: int = 1, meldung: str | None = None,
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                  user: User = Depends(current_user)):
    upd = _get(db, upd_id, user)
    if status is None and not q and not grund and (upd.summary or {}).get("offen"):
        status = "offen"  # zuerst nur das, was geprüft werden muss
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
        "step": 4, "reviewers": reviewers, "fertig": bool(fertig and upd.adopted_list_id),
        "ai_targets": db.scalar(select(func.count(PriceUpdateItem.id)).where(
            PriceUpdateItem.update_id == upd_id, PriceUpdateItem.reviewed_at.is_(None),
            PriceUpdateItem.status.in_(("NICHT_IN_HERSTELLERLISTE", "NICHT_EINDEUTIG")))),
        "all_rules": db.scalars(select(Rule).where(Rule.deleted.is_(False), Rule.owner_id == upd.created_by)
                                .order_by(Rule.name)).all(),
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
    upd = _get(db, upd_id, user)
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
        elif action in ("ki_uebernehmen", "ki_ablehnen"):
            decide_ai_hint(db, upd, item, action == "ki_uebernehmen", user.id)
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
    upd = _get(db, upd_id, user)
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
    upd = _get(db, upd_id, user)
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


@router.post("/aktualisierungen/{upd_id}/uebernehmen", dependencies=[Depends(check_csrf)])
async def adopt(request: Request, upd_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    upd = _get(db, upd_id, user)
    form = await request.form()
    if form.get("bestaetigt") != "ja":
        return _back(upd_id, form, "Bitte das Häkchen zur Bestätigung setzen")
    try:
        pl = adopt_as_current(db, upd, user.id)
    except ValueError as e:
        return _back(upd_id, form, str(e))
    audit(db, user, "abgleich_uebernommen", "price_update", upd.id, {"neue_liste": pl.id}, client_ip(request))
    return _back(upd_id, form, f"Als aktuelle Liste „{pl.name}“ gespeichert. Sie ist beim nächsten Abgleich vorausgewählt.")


@router.post("/aktualisierungen/{upd_id}/ausnahmen", dependencies=[Depends(check_csrf)])
async def article_exceptions(request: Request, upd_id: int, db: Session = Depends(get_db),
                             user: User = Depends(current_user)):
    """Ausgewählte Artikel anders kalkulieren (Faktor oder Regel) bzw. zurück auf die Standardregel."""
    upd = _get(db, upd_id, user)
    form = await request.form()
    ids = [int(v) for v in form.getlist("item") if str(v).isdigit()]
    items = [i for i in db.scalars(select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd.id,
                                                                PriceUpdateItem.id.in_(ids)))] if ids else []
    if not items:
        return _back(upd_id, form, "Keine Artikel ausgewählt (Häkchen in der ersten Spalte)")
    action = str(form.get("action") or "")
    rule = None
    try:
        if action == "setzen":
            raw_factor = str(form.get("factor") or "").strip()
            rule_raw = str(form.get("rule_id") or "")
            if raw_factor and rule_raw:
                raise ValueError("Entweder Faktor oder Regel angeben, nicht beides")
            if raw_factor:
                f = parse_amount(raw_factor, ",")
                if not f.ok or not Decimal(0) < f.value <= Decimal(100):
                    raise ValueError(f"Faktor „{raw_factor[:20]}“ ungültig")
                mids = {i.manufacturer_id for i in items}
                if len(mids) != 1 or None in mids:
                    raise ValueError("Faktor geht nur für Artikel eines Herstellers")
                rule = rule_for_factor(db, db.get(Manufacturer, mids.pop()), f.value, user)
            elif rule_raw.isdigit():
                rule = db.get(Rule, int(rule_raw))
                if rule is None or rule.deleted or rule.owner_id != upd.created_by:
                    raise ValueError("Regel nicht gefunden")
            else:
                raise ValueError("Faktor (z. B. 2,8) oder Regel angeben")
        elif action != "entfernen":
            raise ValueError("Unbekannte Aktion")
    except ValueError as e:
        db.rollback()
        return _back(upd_id, form, str(e))
    changed = set_article_rule(db, upd, items, rule)
    db.flush()
    refresh_summary(db, upd)
    audit(db, user, "artikel_ausnahme_" + action, "price_update", upd.id,
          {"artikel": changed, "regel": rule.id if rule else None}, client_ip(request))
    what = f"Regel „{rule.name}“" if rule else "Standardregel"
    return _back(upd_id, form, f"{len(changed)} Artikel: ab jetzt {what} (gilt auch in künftigen Abgleichen). "
                               "Neu berechnete Positionen bitte prüfen.")


@router.post("/aktualisierungen/{upd_id}/ki", dependencies=[Depends(check_csrf)])
def ai_check(request: Request, upd_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Fehlende/unklare Artikel von der KI einschätzen lassen (Hintergrundjob, nur Vorschläge)."""
    from backend.jobs.runner import enqueue
    from backend.models.entities import Job

    upd = _get(db, upd_id, user)
    running = db.scalars(select(Job).where(Job.type == "AI_UPDATE_MATCH", Job.status.in_(("WARTEND", "LAEUFT")))).all()
    for job in running:
        if (job.params or {}).get("update_id") == upd.id:
            return RedirectResponse(f"/jobs/{job.id}", status_code=303)
    job = enqueue(db, "AI_UPDATE_MATCH", {"update_id": upd.id}, user)
    audit(db, user, "ki_pruefung_abgleich", "price_update", upd.id, {"job": job.id}, client_ip(request))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/aktualisierungen/{upd_id}/abschliessen", dependencies=[Depends(check_csrf)])
async def finish(request: Request, upd_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Ein Klick: als aktuelle Liste übernehmen und die fertige Excel-Liste herunterladen."""
    upd = _get(db, upd_id, user)
    form = await request.form()
    if not upd.adopted_list_id:
        try:
            pl = adopt_as_current(db, upd, user.id)
        except ValueError as e:
            return _back(upd_id, form, str(e))
        audit(db, user, "abgleich_uebernommen", "price_update", upd.id, {"neue_liste": pl.id}, client_ip(request))
    return RedirectResponse(f"/aktualisierungen/{upd_id}?fertig=1", status_code=303)
