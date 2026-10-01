from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.api.deps import current_user
from backend.api.render import render
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import Article, ImportMessage, Job, Manufacturer, PriceList, User

router = APIRouter()
STATUSES = ("OK", "WARNUNG", "UNKLAR", "FEHLER")
LEVELS = ("FEHLER", "UNKLAR", "WARNUNG")


def page_info(total: int, page: int, size: int) -> dict:
    pages = max(1, ceil(total / size))
    page = min(max(page, 1), pages)
    return {"page": page, "pages": pages, "total": total, "offset": (page - 1) * size}


def query_articles(db: Session, list_id: int, status: str | None, q: str | None, page: int, size: int):
    stmt = select(Article).where(Article.price_list_id == list_id)
    if status in STATUSES:
        stmt = stmt.where(Article.status == status)
    if q:
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(Article.article_number.ilike(like), Article.description.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    info = page_info(total, page, size)
    rows = db.scalars(
        stmt.options(selectinload(Article.prices)).order_by(Article.source_row)
        .offset(info["offset"]).limit(size)
    ).all()
    return rows, info


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    lists = db.scalars(select(PriceList).order_by(PriceList.uploaded_at.desc()).limit(10)).all()
    stats = {
        "lists": db.scalar(select(func.count(PriceList.id)).where(PriceList.status == "IMPORTIERT")),
        "articles": db.scalar(select(func.count(Article.id))),
        "manufacturers": db.scalar(select(func.count(Manufacturer.id))),
    }
    jobs = db.scalars(select(Job).where(Job.status.in_(("WARTEND", "LAEUFT"))).order_by(Job.id)).all()
    return render(request, "dashboard.html", {"lists": lists, "stats": stats, "jobs": jobs,
                                              "memory_mb": process_memory_mb()})


def process_memory_mb() -> int | None:
    """Aktueller Speicherverbrauch des App-Prozesses (Linux /proc)."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


@router.get("/listen")
def price_lists(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    lists = db.scalars(
        select(PriceList).options(selectinload(PriceList.manufacturer)).order_by(PriceList.uploaded_at.desc())
    ).all()
    return render(request, "price_lists.html", {"lists": lists})


@router.get("/listen/{list_id}")
def price_list(request: Request, list_id: int, status: str | None = None, q: str | None = None,
               page: int = 1, db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               _user: User = Depends(current_user)):
    pl = db.get(PriceList, list_id)
    if pl is None:
        raise HTTPException(404, "Preisliste nicht gefunden")
    rows, info = query_articles(db, list_id, status, q, page, settings.page_size)
    manufacturers = {m.id: m.name for m in db.scalars(select(Manufacturer))}
    return render(request, "price_list.html", {
        "pl": pl, "rows": rows, "info": info, "status": status if status in STATUSES else None,
        "q": q or "", "statuses": STATUSES, "manufacturers": manufacturers,
    })


@router.get("/listen/{list_id}/meldungen")
def messages(request: Request, list_id: int, level: str | None = None, page: int = 1,
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
             _user: User = Depends(current_user)):
    pl = db.get(PriceList, list_id)
    if pl is None:
        raise HTTPException(404, "Preisliste nicht gefunden")
    stmt = select(ImportMessage).where(ImportMessage.price_list_id == list_id)
    if level in LEVELS:
        stmt = stmt.where(ImportMessage.level == level)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    info = page_info(total, page, settings.page_size)
    rows = db.scalars(stmt.order_by(ImportMessage.source_row, ImportMessage.id)
                      .offset(info["offset"]).limit(settings.page_size)).all()
    return render(request, "messages.html", {
        "pl": pl, "rows": rows, "info": info, "level": level if level in LEVELS else None, "levels": LEVELS,
    })
