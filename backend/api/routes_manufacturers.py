"""Hersteller: Kürzel, Kalkulation (Standardregel + Serien-Ausnahmen), Herstellerliste (EK/UVP, Währung)."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user, require_admin
from backend.api.render import render
from backend.comparison.update import normalize_exception, normalize_series
from backend.database.engine import get_db
from backend.excel.numbers import SUPPORTED_CURRENCIES, parse_amount
from backend.models.entities import Article, Manufacturer, Rule, RuleException, User
from backend.services.audit import audit
from backend.services.manufacturers import normalize_code, validate_code, with_code

router = APIRouter()
MATCH_TYPES = {"SERIE": "Serie / Kategorie ist", "PREFIX": "Artikelnummer beginnt mit"}


def _rules(db: Session):
    return db.scalars(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name)).all()


def _jsonable(d: dict) -> dict:
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in d.items()}


def _list_page(request: Request, db: Session, error: str | None = None, status_code: int = 200):
    counts = dict(db.execute(select(RuleException.manufacturer_id, func.count())
                             .group_by(RuleException.manufacturer_id)).all())
    return render(request, "manufacturers.html", {
        "manufacturers": db.scalars(select(Manufacturer).order_by(Manufacturer.name)).all(),
        "rules": {r.id: r for r in _rules(db)}, "exception_counts": counts, "error": error},
        status_code=status_code)


def _edit_page(request: Request, db: Session, m: Manufacturer, error: str | None = None, status_code: int = 200,
               message: str | None = None):
    exceptions = db.scalars(select(RuleException).where(RuleException.manufacturer_id == m.id)
                            .order_by(RuleException.match_type, RuleException.value)).all()
    return render(request, "manufacturer_edit.html", {
        "m": m, "rules": _rules(db), "exceptions": exceptions, "match_types": MATCH_TYPES,
        "currencies": SUPPORTED_CURRENCIES, "error": error, "message": message}, status_code=status_code)


def _get(db: Session, mid: int) -> Manufacturer:
    m = db.get(Manufacturer, mid)
    if m is None:
        raise HTTPException(404, "Hersteller nicht gefunden")
    return m


@router.get("/hersteller")
def manufacturers(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return _list_page(request, db)


@router.get("/hersteller/{mid}")
def manufacturer_edit(request: Request, mid: int, meldung: str | None = None, db: Session = Depends(get_db),
                      _user: User = Depends(current_user)):
    return _edit_page(request, db, _get(db, mid), message=meldung)


def _amount(form, key: str):
    raw = str(form.get(key) or "").strip()
    return parse_amount(raw, ",") if raw else None


@router.post("/hersteller", dependencies=[Depends(check_csrf)])
async def save_manufacturer(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    form = await request.form()
    mid = str(form.get("id") or "")
    current = db.get(Manufacturer, int(mid)) if mid.isdigit() else None
    if mid.isdigit() and current is None:
        raise HTTPException(404, "Hersteller nicht gefunden")
    name = str(form.get("name") or "").strip()[:200]
    aliases = [a.strip()[:200] for a in str(form.get("aliases") or "").split(";") if a.strip()][:50]
    code = normalize_code(str(form.get("code") or ""))
    rule_raw = str(form.get("default_rule_id") or "")
    rule_id = int(rule_raw) if rule_raw.isdigit() else None
    # Neuanlage aus der Übersicht schickt nur Name/Kürzel: übrige Felder mit Standardwerten
    full = current is not None or "list_basis" in form
    ignore = form.get("ignore_leading_zeros") == "1" if full or "ignore_leading_zeros" in form else True
    list_basis = str(form.get("list_basis") or "EK")
    discount = _amount(form, "dealer_discount")
    threshold = _amount(form, "review_threshold") or parse_amount("10", ",")
    list_currency = str(form.get("list_currency") or "EUR")
    rate = _amount(form, "exchange_rate")

    errors = []
    clash = db.scalar(select(Manufacturer).where(Manufacturer.name == name))
    if not name:
        errors.append("Name fehlt")
    elif clash and (current is None or clash.id != current.id):
        errors.append("Name existiert bereits")
    code_error = validate_code(db, code, current.id if current else None)
    if code_error:
        errors.append(code_error)
    if rule_id is not None:
        rule = db.get(Rule, rule_id)
        if rule is None or rule.deleted:
            errors.append("Regel nicht gefunden")
    if list_basis not in ("EK", "UVP"):
        errors.append("Herstellerliste enthält: EK oder UVP wählen")
    if discount is not None and (not discount.ok or not 0 <= discount.value < 100):
        errors.append("Händlerrabatt muss zwischen 0 und 100 % liegen")
    elif list_basis == "UVP" and discount is None:
        errors.append("Bei UVP-Listen ist der Händlerrabatt Pflicht (EK = UVP - Händlerrabatt)")
    if not threshold.ok or not 0 < threshold.value <= 100:
        errors.append("Prüfschwelle muss zwischen 0 und 100 % liegen")
    if list_currency not in SUPPORTED_CURRENCIES:
        errors.append("Währung der Herstellerliste ungültig")
    elif list_currency != "EUR":
        if rate is None:
            errors.append(f"Umrechnungskurs fehlt: 1 {list_currency} = ? EUR (z. B. 0,095)")
        elif not rate.ok or not 0 < rate.value <= 1000:
            errors.append("Umrechnungskurs muss eine Zahl größer 0 sein")
    if errors:
        if current:
            return _edit_page(request, db, current, "; ".join(errors), 400)
        return _list_page(request, db, "; ".join(errors), 400)

    values = {"name": name, "aliases": aliases, "ignore_leading_zeros": ignore, "code": code,
              "default_rule_id": rule_id, "list_basis": list_basis,
              "dealer_discount": discount.value if discount else None, "review_threshold": threshold.value,
              "list_currency": list_currency, "exchange_rate": rate.value if rate and list_currency != "EUR" else None}
    if current:
        before = {k: getattr(current, k) for k in values}
        for k, v in values.items():
            setattr(current, k, v)
        audit(db, admin, "hersteller_geaendert", "manufacturer", current.id,
              {"vorher": _jsonable(before), "nachher": _jsonable(values)}, client_ip(request))
        return RedirectResponse(f"/hersteller/{current.id}?meldung=Gespeichert", status_code=303)
    m = Manufacturer(**values)
    db.add(m)
    db.flush()
    audit(db, admin, "hersteller_angelegt", "manufacturer", m.id, _jsonable(values), client_ip(request))
    return RedirectResponse(f"/hersteller/{m.id}?meldung=Angelegt. Jetzt Kalkulation und Herstellerliste einstellen.",
                            status_code=303)


@router.post("/hersteller/{mid}/ausnahmen", dependencies=[Depends(check_csrf)])
async def add_exception(request: Request, mid: int, db: Session = Depends(get_db),
                        admin: User = Depends(require_admin)):
    m = _get(db, mid)
    form = await request.form()
    match_type = str(form.get("match_type") or "")
    value = str(form.get("value") or "").strip()[:200]
    note = str(form.get("note") or "").strip()[:200] or None
    rule_raw = str(form.get("rule_id") or "")
    rule = db.get(Rule, int(rule_raw)) if rule_raw.isdigit() else None
    errors = []
    if match_type not in MATCH_TYPES:
        errors.append("Art der Ausnahme wählen")
    if not value:
        errors.append("Serie bzw. Nummernanfang eingeben")
    if rule is None or rule.deleted:
        errors.append("Regel für die Ausnahme wählen")
    norm = normalize_exception(match_type, value) if not errors else ""
    if not errors and not norm:
        errors.append("Wert ist leer")
    if not errors and db.scalar(select(RuleException).where(RuleException.manufacturer_id == m.id,
                                                            RuleException.match_type == match_type,
                                                            RuleException.value_normalized == norm)):
        errors.append("Diese Ausnahme gibt es schon")
    if errors:
        return _edit_page(request, db, m, "; ".join(errors), 400)
    ex = RuleException(manufacturer_id=m.id, match_type=match_type, value=value, value_normalized=norm,
                       rule_id=rule.id, note=note)
    db.add(ex)
    db.flush()
    audit(db, admin, "ausnahme_angelegt", "rule_exception", ex.id,
          {"hersteller": m.id, "typ": match_type, "wert": value, "regel": rule.id}, client_ip(request))
    return RedirectResponse(f"/hersteller/{m.id}?{urlencode({'meldung': _hit_message(db, m, ex)})}", status_code=303)


def _hit_message(db: Session, m: Manufacturer, ex: RuleException) -> str:
    """Rückmeldung, ob die Ausnahme in den vorhandenen Listen überhaupt greift (Tippfehler sofort sehen)."""
    stmt = select(Article.article_number, Article.category).where(Article.manufacturer_id == m.id)
    if ex.match_type == "PREFIX":
        stmt = stmt.where(Article.article_number_normalized.like(f"{ex.value_normalized}%"))
    else:
        stmt = stmt.where(Article.category.is_not(None))
    rows = db.execute(stmt).all()
    if ex.match_type == "SERIE":
        rows = [r for r in rows if normalize_series(r.category) == ex.value_normalized]
    numbers = sorted({r.article_number for r in rows if r.article_number})
    if numbers:
        sample = ", ".join(with_code(n, m.code) for n in numbers[:5])
        return f"Ausnahme gespeichert. Passt in den vorhandenen Listen auf {len(numbers)} Artikelnummer(n), z. B. {sample}."
    hint = (f" Artikelnummern werden ohne Kürzel {m.code} gespeichert – Nummernanfang ohne Kürzel eingeben."
            if ex.match_type == "PREFIX" and m.code and ex.value_normalized.startswith(m.code) else "")
    return f"Ausnahme gespeichert. ACHTUNG: passt bisher auf keinen Artikel in den vorhandenen Listen.{hint}"


@router.post("/hersteller/{mid}/ausnahmen/{ex_id}/loeschen", dependencies=[Depends(check_csrf)])
async def delete_exception(request: Request, mid: int, ex_id: int, db: Session = Depends(get_db),
                           admin: User = Depends(require_admin)):
    m = _get(db, mid)
    ex = db.get(RuleException, ex_id)
    if ex is None or ex.manufacturer_id != m.id:
        raise HTTPException(404, "Ausnahme nicht gefunden")
    form = await request.form()
    if form.get("bestaetigt") != "ja":
        return _edit_page(request, db, m, "Zum Löschen das Häkchen „sicher“ setzen", 400)
    audit(db, admin, "ausnahme_geloescht", "rule_exception", ex.id,
          {"hersteller": m.id, "typ": ex.match_type, "wert": ex.value, "regel": ex.rule_id}, client_ip(request))
    db.delete(ex)
    return RedirectResponse(f"/hersteller/{m.id}?meldung=Ausnahme gelöscht", status_code=303)
