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
from backend.services.access import get_visible, visible
from backend.services.manufacturers import code_map, search_conditions

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
        q = q.strip()[:100]
        like = f"%{q}%"
        stmt = stmt.where(or_(Article.article_number.ilike(like), Article.description.ilike(like),
                              *search_conditions(db, q, Article.article_number, Article.manufacturer_id)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    info = page_info(total, page, size)
    rows = db.scalars(
        stmt.options(selectinload(Article.prices)).order_by(Article.source_row)
        .offset(info["offset"]).limit(size)
    ).all()
    return rows, info


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from backend.services.dashboard import build

    jobs = db.scalars(select(Job).where(Job.status.in_(("WARTEND", "LAEUFT"))).order_by(Job.id)).all()
    return render(request, "dashboard.html", {**build(db, user), "jobs": jobs, "memory_mb": process_memory_mb()})


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
def price_lists(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lists = db.scalars(visible(
        select(PriceList).options(selectinload(PriceList.manufacturer)).order_by(PriceList.uploaded_at.desc()),
        PriceList, user)).all()
    owners = {u.id: u.username for u in db.scalars(select(User))} if user.role == "admin" else {}
    return render(request, "price_lists.html", {"lists": lists, "owners": owners})


@router.get("/listen/{list_id}")
def price_list(request: Request, list_id: int, status: str | None = None, q: str | None = None,
               page: int = 1, db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               user: User = Depends(current_user)):
    pl = get_visible(db, PriceList, list_id, user)
    rows, info = query_articles(db, list_id, status, q, page, settings.page_size)
    manufacturers = {m.id: m.name for m in db.scalars(select(Manufacturer))}
    return render(request, "price_list.html", {
        "pl": pl, "rows": rows, "info": info, "status": status if status in STATUSES else None,
        "q": q or "", "statuses": STATUSES, "manufacturers": manufacturers, "codes": code_map(db),
    })


@router.get("/listen/{list_id}/meldungen")
def messages(request: Request, list_id: int, level: str | None = None, page: int = 1,
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
             user: User = Depends(current_user)):
    pl = get_visible(db, PriceList, list_id, user)
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
