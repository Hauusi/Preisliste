"""Neue Artikel unterm Jahr aufnehmen: einfügen -> Bestätigungsliste -> in die aktuelle EK/VK-Liste."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user
from backend.api.render import render
from backend.database.engine import get_db
from backend.models.entities import User
from backend.services.audit import audit
from backend.services.new_articles import MAX_LINES, add_rows, analyze

router = APIRouter()


def _page(request, text="", rows=None, error=None, added=None, status_code=200):
    ok = [r for r in rows or [] if r.ok]
    return render(request, "new_articles.html", {"text": text, "rows": rows, "ok_count": len(ok), "error": error,
                                                 "added": added, "max_lines": MAX_LINES}, status_code=status_code)


@router.get("/neue-artikel")
def form(request: Request, _user: User = Depends(current_user)):
    return _page(request)


@router.post("/neue-artikel", dependencies=[Depends(check_csrf)])
async def check(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    data = await request.form()
    text = str(data.get("text") or "")[:200_000]
    if not text.strip():
        return _page(request, text, error="Bitte Artikelnummern einfügen", status_code=400)
    try:
        rows = analyze(db, text)
    except ValueError as e:
        return _page(request, text, error=str(e), status_code=400)
    return _page(request, text, rows)


@router.post("/neue-artikel/aufnehmen", dependencies=[Depends(check_csrf)])
async def add(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = await request.form()
    text = str(data.get("text") or "")[:200_000]
    selected = {int(v) for v in data.getlist("line") if str(v).isdigit()}
    try:
        rows = analyze(db, text)  # alles neu prüfen, nichts aus dem Formular übernehmen
    except ValueError as e:
        return _page(request, text, error=str(e), status_code=400)
    if data.get("bestaetigt") != "ja":
        return _page(request, text, rows, error="Bitte das Häkchen zur Bestätigung setzen", status_code=400)
    if not selected:
        return _page(request, text, rows, error="Keine Artikel ausgewählt", status_code=400)
    added = add_rows(db, rows, selected)
    audit(db, user, "neue_artikel_aufgenommen", "price_list", None, {
        "artikel": [{"liste": r.target.id, "artikel": a.id, "nummer": f"{r.manufacturer.code}{r.number}",
                     "ek": str(r.ek), "vk": str(r.vk), "regel": r.rule_label} for r, a in added]}, client_ip(request))
    return _page(request, "", None, added=added)
