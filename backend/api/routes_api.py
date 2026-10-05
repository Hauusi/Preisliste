"""JSON-Endpunkte (Status, Listen, Artikel). Serverseitig paginiert."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.provider import cached_status
from backend.api.deps import current_user
from backend.api.routes_lists import query_articles
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import PriceList, User
from backend.services.access import get_visible, visible
from backend.services.manufacturers import code_map, with_code

router = APIRouter(prefix="/api")


@router.get("/status")
def status(settings: Settings = Depends(get_settings), _user: User = Depends(current_user)):
    s = cached_status(settings)
    return {"ki": {"aktiv": s.active, "anbieter": s.provider, "modell": s.model, "meldung": s.message,
                   "geladen_mb": s.loaded_mb}}


@router.get("/price-lists")
def price_lists(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [
        {"id": pl.id, "name": pl.name, "status": pl.status, "datei": pl.source_file,
         "hochgeladen": pl.uploaded_at.isoformat(), "zusammenfassung": pl.summary}
        for pl in db.scalars(visible(select(PriceList).order_by(PriceList.id.desc()), PriceList, user))
    ]


@router.get("/price-lists/{list_id}/articles")
def articles(list_id: int, status: str | None = None, q: str | None = None, page: int = 1,
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
             user: User = Depends(current_user)):
    get_visible(db, PriceList, list_id, user)
    rows, info = query_articles(db, list_id, status, q, page, settings.page_size)
    codes = code_map(db)
    return {
        "seite": info["page"], "seiten": info["pages"], "gesamt": info["total"],
        "artikel": [
            {
                "id": a.id, "zeile": a.source_row, "artikelnummer": a.article_number,
                "artikelnummer_anzeige": with_code(a.article_number, codes.get(a.manufacturer_id)),
                "bezeichnung": a.description, "status": a.status,
                "preise": [
                    {"typ": p.price_type, "betrag": format(p.amount, "f"), "waehrung": p.currency,
                     "ab_menge": format(p.min_quantity, "f") if p.min_quantity is not None else None}
                    for p in a.prices
                ],
            }
            for a in rows
        ],
    }
