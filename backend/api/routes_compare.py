from __future__ import annotations

import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.api.deps import check_csrf, client_ip, current_user, require_admin
from backend.api.render import render
from backend.api.routes_lists import page_info
from backend.comparison.service import COMPARE_TYPES, STATUS_LABELS, STATUSES, decide, run_comparison
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.excel.numbers import parse_amount
from backend.models.entities import (
    Article,
    CalculationResult,
    CalculationRun,
    Job,
    Comparison,
    ComparisonItem,
    Manufacturer,
    PriceList,
    Rule,
    User,
)
from backend.excel.export import export_calculation, export_comparison
from backend.jobs.runner import enqueue
from backend.services.audit import audit
from backend.services.manufacturers import code_map, normalize_code, search_conditions, validate_code
from backend.services.rules import current_version, run_calculation

router = APIRouter()


def _positive(text, default=Decimal(1)) -> Decimal | None:
    if text in (None, ""):
        return default
    p = parse_amount(str(text), ",")
    return p.value if p.ok and p.value > 0 else None


def _imported(db: Session):
    return db.scalars(select(PriceList).where(PriceList.status == "IMPORTIERT").order_by(PriceList.id.desc())).all()


def _rules(db: Session):
    return db.scalars(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name)).all()


# ---------- Kalkulation ----------

@router.get("/listen/{list_id}/kalkulation")
def calc_form(request: Request, list_id: int, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    pl = db.get(PriceList, list_id)
    if pl is None or pl.status != "IMPORTIERT":
        raise HTTPException(404, "Preisliste nicht gefunden")
    runs = db.scalars(select(CalculationRun).where(CalculationRun.price_list_id == list_id)
                      .options(selectinload(CalculationRun.rule_version)).order_by(CalculationRun.id.desc())).all()
    rule_names = {r.id: r.name for r in db.scalars(select(Rule))}
    preselect, hint = default_rule_for_list(db, pl)
    mid = list_manufacturer(db, pl)
    return render(request, "calc_form.html", {
        "pl": pl, "rules": _rules(db), "runs": runs, "rule_names": rule_names, "error": None,
        "preselect": preselect, "preselect_hint": hint, "step": 5, "list_manufacturer": db.get(Manufacturer, mid) if mid else None,
        "article_count": db.scalar(select(func.count(Article.id)).where(Article.price_list_id == pl.id)),
        **_update_defaults(db, pl, mid),
    })


def _update_defaults(db: Session, pl: PriceList, mid: int | None) -> dict:
    """Vorauswahl für 'Neue Preisliste nur mit unseren Artikeln': ältere Liste desselben Herstellers."""
    from backend.api.routes_updates import main_price_type

    others = [o for o in _imported(db) if o.id != pl.id]
    same = [o for o in others if mid and list_manufacturer(db, o) == mid and o.id < pl.id]
    return {"update_bases": others, "update_base_default": same[0].id if same else None,
            "update_price_type": main_price_type(db, pl.id)}


def list_manufacturer(db: Session, pl: PriceList) -> int | None:
    """Hersteller der Liste: fest gewählt oder der einzige Hersteller der Artikel."""
    if pl.manufacturer_id:
        return pl.manufacturer_id
    mids = set(db.scalars(select(distinct(Article.manufacturer_id)).where(Article.price_list_id == pl.id,
                                                                         Article.manufacturer_id.is_not(None))))
    return mids.pop() if len(mids) == 1 else None


def default_rule_for_list(db: Session, pl: PriceList) -> tuple[int | None, str | None]:
    """Standardregel des Herstellers als Vorauswahl. Bei mehreren Herstellern mit Regel keine Vorauswahl."""
    mids = set(db.scalars(select(distinct(Article.manufacturer_id)).where(Article.price_list_id == pl.id,
                                                                         Article.manufacturer_id.is_not(None))))
    with_rule = [m for m in db.scalars(select(Manufacturer).where(Manufacturer.id.in_(mids)))
                 if m.default_rule_id and not db.get(Rule, m.default_rule_id).deleted]
    if len(with_rule) == 1:
        m = with_rule[0]
        label = f"{m.name} ({m.code})" if m.code else m.name
        return m.default_rule_id, f"Vorausgewählt: Standardregel von {label}"
    if len(with_rule) > 1:
        return None, "Mehrere Hersteller mit unterschiedlichen Standardregeln in dieser Liste, bitte Regel wählen"
    return None, None


@router.post("/listen/{list_id}/kalkulation", dependencies=[Depends(check_csrf)])
async def calc_run(request: Request, list_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    pl = db.get(PriceList, list_id)
    if pl is None or pl.status != "IMPORTIERT":
        raise HTTPException(404, "Preisliste nicht gefunden")
    form = await request.form()
    rule_id = form.get("rule_id")
    rule = db.get(Rule, int(rule_id)) if rule_id and str(rule_id).isdigit() else None
    qty = _positive(form.get("quantity"))
    if rule is None or rule.deleted or qty is None:
        runs = db.scalars(select(CalculationRun).where(CalculationRun.price_list_id == list_id)).all()
        return render(request, "calc_form.html", {"pl": pl, "rules": _rules(db), "runs": runs, "rule_names": {},
                                                  "error": "Regel wählen und Menge > 0 angeben"}, status_code=400)
    rv = current_version(db, rule)
    run = run_calculation(db, pl.id, rv, qty, user)
    audit(db, user, "kalkulation", "calculation_run", run.id,
          {"liste": pl.id, "regel": rule.id, "version": rv.version, "menge": str(qty)}, client_ip(request))
    return RedirectResponse(f"/kalkulationen/{run.id}", status_code=303)


@router.get("/kalkulationen/{run_id}")
def calc_results(request: Request, run_id: int, status: str | None = None, page: int = 1,
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                 _user: User = Depends(current_user)):
    run = db.get(CalculationRun, run_id)
    if run is None:
        raise HTTPException(404, "Kalkulation nicht gefunden")
    stmt = select(CalculationResult).where(CalculationResult.run_id == run_id)
    if status in ("OK", "FEHLER"):
        stmt = stmt.where(CalculationResult.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    info = page_info(total, page, settings.page_size)
    rows = db.scalars(stmt.options(selectinload(CalculationResult.article)).order_by(CalculationResult.id)
                      .offset(info["offset"]).limit(settings.page_size)).all()
    rule = db.get(Rule, run.rule_version.rule_id)
    pl = db.get(PriceList, run.price_list_id)
    mid = list_manufacturer(db, pl)
    others = [o for o in _imported(db) if o.id != pl.id]
    same = [o for o in others if mid and list_manufacturer(db, o) == mid and o.id < pl.id]
    existing = db.scalars(select(Comparison).where(Comparison.new_price_list_id == pl.id)
                          .order_by(Comparison.id.desc())).all()
    return render(request, "calc_results.html", {
        "run": run, "rule": rule, "rows": rows, "info": info, "status": status, "pl": pl, "codes": code_map(db),
        "step": 6, "others": others, "compare_default": same[0].id if same else None, "comparisons": existing,
    })


# ---------- Vergleiche ----------

def _list_ctx(db: Session, error: str | None = None) -> dict:
    items = db.scalars(select(Comparison).options(selectinload(Comparison.old_list), selectinload(Comparison.new_list),
                                                  selectinload(Comparison.manufacturer))
                       .order_by(Comparison.id.desc())).all()
    return {
        "comparisons": items, "lists": _imported(db), "rules": _rules(db), "types": COMPARE_TYPES,
        "manufacturers": db.scalars(select(Manufacturer).order_by(Manufacturer.name)).all(), "error": error,
        "labels": STATUS_LABELS, "statuses": STATUSES,
    }


@router.get("/vergleiche")
def comparisons(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return render(request, "comparisons.html", _list_ctx(db))


@router.post("/vergleiche", dependencies=[Depends(check_csrf)])
async def create_comparison(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    errors = []

    def as_int(key):
        v = form.get(key)
        return int(v) if v and str(v).isdigit() else None

    old_id, new_id, mfr_id = as_int("old_id"), as_int("new_id"), as_int("manufacturer_id")
    price_type = form.get("price_type") or "LISTE"
    qty = _positive(form.get("quantity"))
    old, new = (db.get(PriceList, old_id) if old_id else None), (db.get(PriceList, new_id) if new_id else None)
    if not old or not new or old.status != "IMPORTIERT" or new.status != "IMPORTIERT":
        errors.append("Alte und neue Liste wählen")
    elif old.id == new.id:
        errors.append("Alte und neue Liste müssen verschieden sein")
    if price_type not in COMPARE_TYPES:
        errors.append("Ungültiger Preistyp")
    if qty is None:
        errors.append("Menge muss größer 0 sein")
    rule_version_id = None
    if price_type == "KALKULIERT":
        rule = db.get(Rule, as_int("rule_id")) if as_int("rule_id") else None
        if rule is None or rule.deleted:
            errors.append("Für kalkulierte Preise eine Regel wählen")
        else:
            rule_version_id = current_version(db, rule).id
    if errors:
        return render(request, "comparisons.html", _list_ctx(db, "; ".join(errors)), status_code=400)
    cmp = Comparison(old_price_list_id=old.id, new_price_list_id=new.id, manufacturer_id=mfr_id,
                     price_type=price_type, rule_version_id=rule_version_id, quantity=qty, created_by=user.id)
    db.add(cmp)
    db.flush()
    summary = run_comparison(db, cmp)
    audit(db, user, "vergleich", "comparison", cmp.id, {"alt": old.id, "neu": new.id, "typ": price_type,
                                                        "zusammenfassung": summary}, client_ip(request))
    return RedirectResponse(f"/vergleiche/{cmp.id}", status_code=303)


def _filtered(db: Session, cmp_id: int, status, manufacturer, category, q):
    stmt = select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id)
    if status == "UNKLAR":
        stmt = stmt.where(ComparisonItem.status.in_(("NICHT_EINDEUTIG", "FEHLER")))
    elif status in STATUSES:
        stmt = stmt.where(ComparisonItem.status == status)
    if manufacturer and manufacturer.isdigit():
        stmt = stmt.where(ComparisonItem.manufacturer_id == int(manufacturer))
    if category:
        stmt = stmt.where(ComparisonItem.category == category)
    if q:
        q = q.strip()[:100]
        like = f"%{q}%"
        stmt = stmt.where(or_(ComparisonItem.article_number.ilike(like), ComparisonItem.description.ilike(like),
                              *search_conditions(db, q, ComparisonItem.article_number,
                                                 ComparisonItem.manufacturer_id)))
    return stmt


def _price_filter(rows, pmin: Decimal | None, pmax: Decimal | None):
    def amount(i):
        return i.new_amount if i.new_amount is not None else i.old_amount
    out = []
    for i in rows:
        a = amount(i)
        if (pmin is not None or pmax is not None) and a is None:
            continue
        if pmin is not None and a < pmin:
            continue
        if pmax is not None and a > pmax:
            continue
        out.append(i)
    return out


@router.get("/vergleiche/{cmp_id}")
def comparison_detail(request: Request, cmp_id: int, status: str | None = None, manufacturer: str | None = None,
                      category: str | None = None, pmin: str | None = None, pmax: str | None = None,
                      q: str | None = None, page: int = 1, db: Session = Depends(get_db),
                      settings: Settings = Depends(get_settings), _user: User = Depends(current_user)):
    cmp = db.get(Comparison, cmp_id)
    if cmp is None:
        raise HTTPException(404, "Vergleich nicht gefunden")
    stmt = _filtered(db, cmp_id, status, manufacturer, category, q)
    lo = parse_amount(pmin, ",").value if pmin else None
    hi = parse_amount(pmax, ",").value if pmax else None
    if lo is not None or hi is not None:
        # Preisfilter in Python, weil Beträge als exakter Dezimaltext gespeichert sind (kein float-Vergleich in SQL)
        all_rows = _price_filter(db.scalars(stmt.order_by(ComparisonItem.id)).all(), lo, hi)
        info = page_info(len(all_rows), page, settings.page_size)
        rows = all_rows[info["offset"]: info["offset"] + settings.page_size]
    else:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        info = page_info(total, page, settings.page_size)
        rows = db.scalars(stmt.order_by(ComparisonItem.id).offset(info["offset"]).limit(settings.page_size)).all()
    categories = [c for c in db.scalars(select(distinct(ComparisonItem.category)).where(
        ComparisonItem.comparison_id == cmp_id, ComparisonItem.category.is_not(None)).order_by(ComparisonItem.category))]
    manufacturers = {m.id: m.name for m in db.scalars(select(Manufacturer))}
    filters = {"status": status or "", "manufacturer": manufacturer or "", "category": category or "",
               "pmin": pmin or "", "pmax": pmax or "", "q": q or ""}
    return render(request, "comparison.html", {
        "cmp": cmp, "rows": rows, "info": info, "filters": filters, "categories": categories,
        "manufacturers": manufacturers, "labels": STATUS_LABELS, "statuses": STATUSES, "error": None,
        "codes": code_map(db),
    })


@router.post("/vergleiche/{cmp_id}/eintrag/{item_id}", dependencies=[Depends(check_csrf)])
async def decide_item(request: Request, cmp_id: int, item_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    cmp = db.get(Comparison, cmp_id)
    item = db.get(ComparisonItem, item_id)
    if cmp is None or item is None or item.comparison_id != cmp_id:
        raise HTTPException(404, "Eintrag nicht gefunden")
    form = await request.form()
    choice = str(form.get("old_id") or "")
    old_id = int(choice) if choice.isdigit() else None
    if choice != "keiner" and old_id is None:
        raise HTTPException(400, "Auswahl fehlt")
    try:
        decide(db, cmp, item, old_id, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, user, "zuordnung_bestaetigt" if old_id else "zuordnung_abgelehnt", "comparison_item", item_id,
          {"vergleich": cmp_id, "alt_artikel": old_id, "neu_artikel": item.new_article_id}, client_ip(request))
    back = str(form.get("back") or "")
    return RedirectResponse(back if back.startswith(f"/vergleiche/{cmp_id}") else f"/vergleiche/{cmp_id}",
                            status_code=303)


def _xlsx(data: bytes, name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80] or "export"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.xlsx"'})


@router.get("/vergleiche/{cmp_id}/export")
def export_cmp(request: Request, cmp_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cmp = db.get(Comparison, cmp_id)
    if cmp is None:
        raise HTTPException(404, "Vergleich nicht gefunden")
    data = export_comparison(db, cmp)
    audit(db, user, "export", "comparison", cmp_id, ip=client_ip(request))
    return _xlsx(data, f"Vergleich_{cmp.old_list.name}_{cmp.new_list.name}_{cmp_id}")


@router.get("/kalkulationen/{run_id}/export")
def export_calc(request: Request, run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = db.get(CalculationRun, run_id)
    if run is None:
        raise HTTPException(404, "Kalkulation nicht gefunden")
    data = export_calculation(db, run)
    audit(db, user, "export", "calculation_run", run_id, ip=client_ip(request))
    return _xlsx(data, f"Kalkulation_{run_id}")


@router.post("/vergleiche/{cmp_id}/ki", dependencies=[Depends(check_csrf)])
def ai_match(request: Request, cmp_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cmp = db.get(Comparison, cmp_id)
    if cmp is None:
        raise HTTPException(404, "Vergleich nicht gefunden")
    running = db.scalar(select(Job).where(Job.type == "AI_MATCH", Job.status.in_(("WARTEND", "LAEUFT"))))
    if running and (running.params or {}).get("comparison_id") == cmp_id:
        return RedirectResponse(f"/jobs/{running.id}", status_code=303)
    job = enqueue(db, "AI_MATCH", {"comparison_id": cmp_id}, user)
    audit(db, user, "ki_zuordnung_gestartet", "comparison", cmp_id, {"job": job.id}, client_ip(request))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/vergleiche/{cmp_id}/neu-berechnen", dependencies=[Depends(check_csrf)])
def recompute(request: Request, cmp_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cmp = db.get(Comparison, cmp_id)
    if cmp is None:
        raise HTTPException(404, "Vergleich nicht gefunden")
    run_comparison(db, cmp)
    audit(db, user, "vergleich_neu_berechnet", "comparison", cmp_id, ip=client_ip(request))
    return RedirectResponse(f"/vergleiche/{cmp_id}", status_code=303)


# ---------- Hersteller ----------

def _manufacturer_page(request: Request, db: Session, error: str | None = None, status_code: int = 200):
    return render(request, "manufacturers.html", {
        "manufacturers": db.scalars(select(Manufacturer).order_by(Manufacturer.name)).all(),
        "rules": _rules(db), "error": error}, status_code=status_code)


@router.get("/hersteller")
def manufacturers(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return _manufacturer_page(request, db)


@router.post("/hersteller", dependencies=[Depends(check_csrf)])
async def save_manufacturer(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    form = await request.form()
    mid = str(form.get("id") or "")
    name = str(form.get("name") or "").strip()[:200]
    aliases = [a.strip()[:200] for a in str(form.get("aliases") or "").split(";") if a.strip()][:50]
    ignore = form.get("ignore_leading_zeros") == "1"
    code = normalize_code(str(form.get("code") or ""))
    rule_raw = str(form.get("default_rule_id") or "")
    rule_id = int(rule_raw) if rule_raw.isdigit() else None
    current = db.get(Manufacturer, int(mid)) if mid.isdigit() else None
    if mid.isdigit() and current is None:
        raise HTTPException(404, "Hersteller nicht gefunden")
    clash = db.scalar(select(Manufacturer).where(Manufacturer.name == name))
    error = None
    if not name:
        error = "Name fehlt"
    elif clash and (current is None or clash.id != current.id):
        error = "Name existiert bereits"
    else:
        error = validate_code(db, code, current.id if current else None)
    if not error and rule_id is not None:
        rule = db.get(Rule, rule_id)
        if rule is None or rule.deleted:
            error = "Regel nicht gefunden"
    if error:
        return _manufacturer_page(request, db, error, 400)
    values = {"name": name, "aliases": aliases, "ignore_leading_zeros": ignore, "code": code,
              "default_rule_id": rule_id}
    if current:
        before = {k: getattr(current, k) for k in values}
        for k, v in values.items():
            setattr(current, k, v)
        audit(db, admin, "hersteller_geaendert", "manufacturer", current.id, {"vorher": before, "nachher": values},
              client_ip(request))
    else:
        m = Manufacturer(**values)
        db.add(m)
        db.flush()
        audit(db, admin, "hersteller_angelegt", "manufacturer", m.id, values, client_ip(request))
    return RedirectResponse("/hersteller", status_code=303)
