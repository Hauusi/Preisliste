"""Preisaktualisierung: neue Liste nur mit unseren Artikeln, Preise aus der Herstellerliste."""

from __future__ import annotations

import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.api.routes_lists import page_info
from backend.comparison.update import STATUS_LABELS, STATUSES, run_update
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.excel.export import export_price_update
from backend.excel.numbers import parse_amount
from backend.models.entities import ArticlePrice, Article, PriceList, PriceUpdate, PriceUpdateItem, Rule, User
from backend.services.audit import audit
from backend.services.manufacturers import code_map, search_conditions
from backend.services.rules import current_version

router = APIRouter()
PRICE_TYPES = ("EK", "LISTE", "UVP")


def main_price_type(db: Session, list_id: int) -> str:
    """Häufigste Preisart einer Liste (Vorauswahl)."""
    row = db.execute(select(ArticlePrice.price_type, func.count()).join(Article)
                     .where(Article.price_list_id == list_id).group_by(ArticlePrice.price_type)
                     .order_by(func.count().desc())).first()
    return row[0] if row else "LISTE"


def _imported(db: Session):
    return db.scalars(select(PriceList).where(PriceList.status == "IMPORTIERT").order_by(PriceList.id.desc())).all()


@router.get("/aktualisierungen")
def updates(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    items = db.scalars(select(PriceUpdate).order_by(PriceUpdate.id.desc())).all()
    rules = db.scalars(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name)).all()
    return render(request, "updates.html", {"updates": items, "lists": _imported(db), "rules": rules,
                                            "types": PRICE_TYPES, "labels": STATUS_LABELS, "error": None})


@router.post("/aktualisierungen", dependencies=[Depends(check_csrf)])
async def create_update(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()

    def as_int(key):
        v = str(form.get(key) or "")
        return int(v) if v.isdigit() else None

    errors = []
    base = db.get(PriceList, as_int("base_id")) if as_int("base_id") else None
    source = db.get(PriceList, as_int("source_id")) if as_int("source_id") else None
    if not base or not source or base.status != "IMPORTIERT" or source.status != "IMPORTIERT":
        errors.append("Unsere Liste und Herstellerliste wählen")
    elif base.id == source.id:
        errors.append("Unsere Liste und Herstellerliste müssen verschieden sein")
    price_type = str(form.get("price_type") or "")
    if price_type not in PRICE_TYPES:
        errors.append("Preisart wählen")
    qty = parse_amount(str(form.get("quantity") or "1"), ",")
    if not qty.ok or qty.value <= 0:
        errors.append("Menge muss größer 0 sein")
    rule_version_id = None
    if as_int("rule_id"):
        rule = db.get(Rule, as_int("rule_id"))
        if rule is None or rule.deleted:
            errors.append("Regel nicht gefunden")
        else:
            rule_version_id = current_version(db, rule).id
    if errors:
        items = db.scalars(select(PriceUpdate).order_by(PriceUpdate.id.desc())).all()
        rules = db.scalars(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name)).all()
        return render(request, "updates.html", {"updates": items, "lists": _imported(db), "rules": rules,
                                                "types": PRICE_TYPES, "labels": STATUS_LABELS,
                                                "error": "; ".join(errors)}, status_code=400)
    upd = PriceUpdate(base_price_list_id=base.id, source_price_list_id=source.id, price_type=price_type,
                      rule_version_id=rule_version_id, quantity=qty.value, created_by=user.id)
    db.add(upd)
    db.flush()
    summary = run_update(db, upd)
    audit(db, user, "preisaktualisierung", "price_update", upd.id,
          {"basis": base.id, "hersteller": source.id, "typ": price_type, "zusammenfassung": summary},
          client_ip(request))
    return RedirectResponse(f"/aktualisierungen/{upd.id}", status_code=303)


@router.get("/aktualisierungen/{upd_id}")
def update_detail(request: Request, upd_id: int, status: str | None = None, q: str | None = None, page: int = 1,
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                  _user: User = Depends(current_user)):
    upd = db.get(PriceUpdate, upd_id)
    if upd is None:
        raise HTTPException(404, "Aktualisierung nicht gefunden")
    stmt = select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd_id)
    if status in STATUSES:
        stmt = stmt.where(PriceUpdateItem.status == status)
    if q:
        q = q.strip()[:100]
        stmt = stmt.where(or_(PriceUpdateItem.article_number.ilike(f"%{q}%"),
                              PriceUpdateItem.description.ilike(f"%{q}%"),
                              *search_conditions(db, q, PriceUpdateItem.article_number,
                                                 PriceUpdateItem.manufacturer_id)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    info = page_info(total, page, settings.page_size)
    rows = db.scalars(stmt.order_by(PriceUpdateItem.id).offset(info["offset"]).limit(settings.page_size)).all()
    return render(request, "update.html", {
        "upd": upd, "rows": rows, "info": info, "status": status if status in STATUSES else "", "q": q or "",
        "statuses": STATUSES, "labels": STATUS_LABELS, "codes": code_map(db), "step": 6,
        "rule": db.get(Rule, upd.rule_version.rule_id) if upd.rule_version else None,
    })


@router.get("/aktualisierungen/{upd_id}/export")
def export(request: Request, upd_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    upd = db.get(PriceUpdate, upd_id)
    if upd is None:
        raise HTTPException(404, "Aktualisierung nicht gefunden")
    data = export_price_update(db, upd)
    audit(db, user, "export", "price_update", upd_id, ip=client_ip(request))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"Neue_Preisliste_{upd.base_list.name}_{upd_id}")[:80]
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
