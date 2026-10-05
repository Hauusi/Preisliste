"""Löschen mit Doppelbestätigung: Papierkorb -> Bestätigungsseite mit Häkchen -> Löschen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.services.access import get_visible
from backend.api.render import render
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import Manufacturer, PriceList, Rule, User
from backend.services import deletion
from backend.services.audit import audit

router = APIRouter()


def _confirm_page(request, *, title, name, action, back, impact, blocked=None, error=None, status_code=200):
    return render(request, "confirm_delete.html", {"title": title, "name": name, "action": action, "back": back,
                                                   "impact": impact, "blocked": blocked, "error": error},
                  status_code=status_code)


async def _confirmed(request: Request) -> bool:
    return (await request.form()).get("bestaetigt") == "ja"


def _list_for(db: Session, list_id: int, user: User) -> PriceList:
    pl = get_visible(db, PriceList, list_id, user)
    if pl.status == "WARTESCHLANGE":
        raise HTTPException(409, "Der Import dieser Liste läuft noch")
    return pl


@router.get("/listen/{list_id}/loeschen")
def confirm_list(request: Request, list_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    pl = _list_for(db, list_id, user)
    return _confirm_page(request, title="Preisliste löschen", name=pl.name, action=f"/listen/{pl.id}/loeschen",
                         back="/listen", impact=deletion.price_list_impact(db, pl))


@router.post("/listen/{list_id}/loeschen", dependencies=[Depends(check_csrf)])
async def do_delete_list(request: Request, list_id: int, db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    pl = _list_for(db, list_id, user)
    if not await _confirmed(request):
        return _confirm_page(request, title="Preisliste löschen", name=pl.name, action=f"/listen/{pl.id}/loeschen",
                             back="/listen", impact=deletion.price_list_impact(db, pl),
                             error="Bitte das Häkchen zur Bestätigung setzen.", status_code=400)
    info = {"name": pl.name, "datei": pl.source_file}
    deletion.delete_price_list(db, pl, settings)
    audit(db, user, "preisliste_geloescht", "price_list", list_id, info, client_ip(request))
    return RedirectResponse("/listen?geloescht=1", status_code=303)


def _manufacturer(db: Session, mid: int, user: User) -> Manufacturer:
    return get_visible(db, Manufacturer, mid, user)


@router.get("/hersteller/{mid}/loeschen")
def confirm_manufacturer(request: Request, mid: int, db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    m = _manufacturer(db, mid, user)
    impact, blocked = deletion.manufacturer_impact(db, m)
    return _confirm_page(request, title="Hersteller löschen", name=f"{m.name}" + (f" ({m.code})" if m.code else ""),
                         action=f"/hersteller/{m.id}/loeschen", back="/hersteller", impact=impact, blocked=blocked)


@router.post("/hersteller/{mid}/loeschen", dependencies=[Depends(check_csrf)])
async def do_delete_manufacturer(request: Request, mid: int, db: Session = Depends(get_db),
                                 user: User = Depends(current_user)):
    m = _manufacturer(db, mid, user)
    impact, blocked = deletion.manufacturer_impact(db, m)
    if blocked or not await _confirmed(request):
        return _confirm_page(request, title="Hersteller löschen", name=m.name, action=f"/hersteller/{m.id}/loeschen",
                             back="/hersteller", impact=impact, blocked=blocked,
                             error=None if blocked else "Bitte das Häkchen zur Bestätigung setzen.", status_code=400)
    info = {"name": m.name, "kuerzel": m.code}
    deletion.delete_manufacturer(db, m)
    audit(db, user, "hersteller_geloescht", "manufacturer", mid, info, client_ip(request))
    return RedirectResponse("/hersteller", status_code=303)


def _rule(db: Session, rule_id: int, user: User) -> Rule:
    rule = get_visible(db, Rule, rule_id, user)
    if rule.deleted:
        raise HTTPException(404, "Regel nicht gefunden")
    return rule


@router.get("/regeln/{rule_id}/loeschen")
def confirm_rule(request: Request, rule_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rule = _rule(db, rule_id, user)
    return _confirm_page(request, title="Regel löschen", name=rule.name, action=f"/regeln/{rule.id}/loeschen",
                         back="/regeln", impact=deletion.rule_impact(db, rule))


@router.post("/regeln/{rule_id}/loeschen", dependencies=[Depends(check_csrf)])
async def do_delete_rule(request: Request, rule_id: int, db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    rule = _rule(db, rule_id, user)
    if not await _confirmed(request):
        return _confirm_page(request, title="Regel löschen", name=rule.name, action=f"/regeln/{rule.id}/loeschen",
                             back="/regeln", impact=deletion.rule_impact(db, rule),
                             error="Bitte das Häkchen zur Bestätigung setzen.", status_code=400)
    deletion.delete_rule(db, rule)
    audit(db, user, "regel_geloescht", "rule", rule_id, {"name": rule.name}, client_ip(request))
    return RedirectResponse("/regeln", status_code=303)
