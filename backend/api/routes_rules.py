from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, current_user, require_admin
from backend.api.render import render
from backend.calculations.engine import MODE_LABELS, PRICE_TYPES, PriceInput, RuleDefinition, calculate
from backend.database.engine import get_db
from backend.excel.numbers import parse_amount
from backend.jobs.runner import enqueue
from backend.models.entities import Job, Manufacturer, Rule, RuleVersion, User
from backend.services.audit import audit
from backend.services.rules import create_rule, current_version, new_version

router = APIRouter()
MAX_STEPS = 12
STEP_TYPES = {
    "discount": "Rabatt %", "surcharge": "Aufschlag %", "multiply": "Faktor (multiplizieren)",
    "fixed": "Fixbetrag (+/-)", "tier": "Staffelpreis für Menge",
    "min_quantity": "Mindestmenge", "round": "Runden auf Schrittweite", "round_ending": "Runden auf Endung",
    "formula": "Formel",
}
VALUE_FIELD = {"discount": "percent", "surcharge": "percent", "multiply": "factor", "fixed": "amount", "tier": "quantity",
               "min_quantity": "quantity", "round": "increment", "round_ending": "ending", "formula": "expression"}


def _num(text: str) -> str:
    """Zahl aus dem Formular (deutsch oder englisch) als Decimal-Text, sonst Originaltext für die Fehlermeldung."""
    parsed = parse_amount(text, "," if "," in text else ".")
    return format(parsed.value, "f") if parsed.ok else text


def parse_rule_form(form) -> tuple[dict, list[str]]:
    steps, errors = [], []
    for i in range(1, MAX_STEPS + 1):
        typ = form.get(f"step_{i}_type") or ""
        if not typ:
            continue
        if typ not in STEP_TYPES:
            errors.append(f"Zeile {i}: unbekannter Schritttyp")
            continue
        value = str(form.get(f"step_{i}_value") or "").strip()
        step: dict = {"type": typ}
        label = str(form.get(f"step_{i}_label") or "").strip()
        if label:
            step["label"] = label[:100]
        step[VALUE_FIELD[typ]] = value if typ == "formula" else _num(value)
        if typ in ("discount", "surcharge"):
            step["base"] = form.get(f"step_{i}_base") or "current"
        if typ == "round":
            step["mode"] = form.get(f"step_{i}_mode") or form.get(f"step_{i}_extra") or "HALF_UP"
        if typ == "round_ending":
            step["direction"] = form.get(f"step_{i}_direction") or form.get(f"step_{i}_extra") or "UP"
            period = str(form.get(f"step_{i}_period") or "").strip()
            if period:
                step["period"] = _num(period)
        steps.append(step)
    data = {
        "start_price": form.get("start_price") or "LISTE",
        "rounding": {"mode": form.get("rounding_mode") or "HALF_UP",
                     "places": form.get("rounding_places") or 2,
                     "timing": form.get("rounding_timing") or "STEP"},
        "steps": steps,
    }
    return data, errors


def _validation_messages(exc: ValidationError) -> list[str]:
    out = []
    for e in exc.errors():
        loc = [str(x) for x in e["loc"]]
        where = f"Schritt {int(loc[1]) + 1}" if len(loc) > 1 and loc[0] == "steps" and loc[1].isdigit() else ".".join(loc)
        msg = e["msg"].removeprefix("Value error, ")
        out.append(f"{where}: {msg}" if where else msg)
    return out


def form_rows(definition: dict | None) -> list[dict]:
    """Alle Schritt-Zeilen; used = belegt oder erste freie Zeile (die übrigen blendet das Skript aus)."""
    steps = (definition or {}).get("steps", [])
    rows = []
    for i in range(MAX_STEPS):
        s = steps[i] if i < len(steps) else {}
        typ = s.get("type", "")
        rows.append({
            "nr": i + 1, "type": typ, "label": s.get("label", ""), "used": i <= len(steps),
            "value": s.get(VALUE_FIELD.get(typ, ""), "") if typ else "",
            "base": s.get("base", "current"), "mode": s.get("mode", "HALF_UP"),
            "direction": s.get("direction", "UP"), "period": s.get("period", ""),
        })
    return rows


STEP_HELP = {
    "discount": "Zieht einen Prozentsatz ab. Beispiel: 15 % vom Ausgangspreis 100,00 = 15,00 Abzug.",
    "surcharge": "Schlägt einen Prozentsatz auf. Beispiel: 4 % Transport vom aktuellen Zwischenpreis.",
    "multiply": "Multipliziert den aktuellen Zwischenpreis. Beispiel: EK 10,00 × 2,6 = 26,00.",
    "fixed": "Addiert einen festen Betrag. Für einen Abzug ein Minus davor schreiben (z. B. -2,50).",
    "tier": "Nimmt den Staffelpreis der Liste für diese Menge als neuen Zwischenpreis.",
    "min_quantity": "Prüft die Bestellmenge. Liegt sie darunter, wird die Position als FEHLER markiert.",
    "round": "Rundet auf eine Schrittweite, z. B. 0,05 oder 1,00.",
    "round_ending": "Rundet auf eine Preisendung, z. B. 0,90 (12,34 wird zu 12,90).",
    "formula": "Eigene Formel, vollständig ausgeschrieben, z. B. current * 2,6 oder start * 1,19 + 3. "
               "Erlaubt: + - * / ( ) min(a; b) max(a; b). Variablen: start (Ausgangspreis), current (Zwischenpreis), "
               "quantity, transport, discount, s1, s2 … (Ergebnis von Schritt 1, 2 …).",
}
VALUE_LABELS = {"discount": "Prozent", "surcharge": "Prozent", "multiply": "Faktor", "fixed": "Betrag", "tier": "Menge",
                "min_quantity": "Mindestmenge", "round": "Schrittweite", "round_ending": "Endung",
                "formula": "Formel"}
DIRECTIONS = {"UP": "aufrunden", "DOWN": "abrunden", "NEAREST": "zur nächsten Endung"}


def _ctx(db: Session, **kw) -> dict:
    return {"step_help": STEP_HELP, "value_labels": VALUE_LABELS, "directions": DIRECTIONS,
            "step_types": STEP_TYPES, "price_types": PRICE_TYPES, "modes": MODE_LABELS, "max_steps": MAX_STEPS,
            "manufacturers": list(db.scalars(select(Manufacturer).order_by(Manufacturer.name))), **kw}


def _rule(db: Session, rule_id: int) -> Rule:
    rule = db.get(Rule, rule_id)
    if rule is None or rule.deleted:
        raise HTTPException(404, "Regel nicht gefunden")
    return rule


@router.get("/regeln")
def rules(request: Request, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    items = db.scalars(select(Rule).where(Rule.deleted.is_(False)).order_by(Rule.name)).all()
    return render(request, "rules.html", {"rules": items})


@router.get("/regeln/neu")
def new_rule_form(request: Request, ki_job: int | None = None, hersteller: int | None = None,
                  zurueck: str | None = None, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    definition: dict = {"start_price": "LISTE", "rounding": {}}
    ai = None
    job = db.get(Job, ki_job) if ki_job else None
    if job and job.type == "AI_RULE" and job.status == "FERTIG" and job.created_by == admin.id:
        ai = job.result or {}
        if ai.get("definition"):
            definition = {**ai["definition"], "rounding": {}}
    m = db.get(Manufacturer, hersteller) if hersteller else None
    return render(request, "rule_edit.html", _ctx(db, rule=None, definition=definition, rows=form_rows(definition),
                                                  errors=[], name=m.name if m else "",
                                                  manufacturer_id=m.id if m else None, ai=ai,
                                                  zurueck=_safe_return(zurueck)))


def _safe_return(url: str | None) -> str | None:
    """Nur interne Rücksprünge in die Kalkulation erlauben (kein offener Redirect)."""
    return url if url and re.fullmatch(r"/listen/\d+/kalkulation|/hersteller/\d+", url) else None


@router.post("/regeln/ki", dependencies=[Depends(check_csrf)])
async def ai_rule(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    form = await request.form()
    text = str(form.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Beschreibung fehlt")
    job = enqueue(db, "AI_RULE", {"text": text[:1000]}, admin)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


async def _save(request: Request, db: Session, admin: User, rule: Rule | None):
    form = await request.form()
    data, errors = parse_rule_form(form)
    name = str(form.get("name") or "").strip()
    if not name:
        errors.append("Name fehlt")
    mid = form.get("manufacturer_id")
    manufacturer_id = int(mid) if mid and str(mid).isdigit() else None
    comment = str(form.get("comment") or "").strip()[:500] or None
    defn = None
    if not errors:
        try:
            defn = RuleDefinition.model_validate(data)
        except ValidationError as exc:
            errors.extend(_validation_messages(exc))
    zurueck = _safe_return(str(form.get("zurueck") or ""))
    if errors:
        return render(request, "rule_edit.html", _ctx(
            db, rule=rule, definition=data, rows=form_rows(data), errors=errors, name=name,
            manufacturer_id=manufacturer_id, zurueck=zurueck), status_code=400)
    if rule is None:
        rule = create_rule(db, name, manufacturer_id, defn, admin, comment)
        audit(db, admin, "regel_angelegt", "rule", rule.id, {"version": 1, "definition": data}, client_ip(request))
        m = db.get(Manufacturer, manufacturer_id) if manufacturer_id else None
        if m is not None and m.default_rule_id is None:
            # Erste Regel eines Herstellers wird seine Standardregel (Vorauswahl bei der Kalkulation)
            m.default_rule_id = rule.id
            audit(db, admin, "hersteller_standardregel", "manufacturer", m.id, {"regel": rule.id}, client_ip(request))
        if zurueck:
            return RedirectResponse(zurueck, status_code=303)
    else:
        rv = new_version(db, rule, name, manufacturer_id, defn, admin, comment)
        audit(db, admin, "regel_geaendert", "rule", rule.id, {"version": rv.version, "definition": data},
              client_ip(request))
    return RedirectResponse(f"/regeln/{rule.id}", status_code=303)


@router.post("/regeln/neu", dependencies=[Depends(check_csrf)])
async def create(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return await _save(request, db, admin, None)


@router.get("/regeln/{rule_id}")
def rule_detail(request: Request, rule_id: int, version: int | None = None, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    rule = _rule(db, rule_id)
    versions = db.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule.id)
                          .order_by(RuleVersion.version.desc())).all()
    shown = next((v for v in versions if v.version == version), None) or current_version(db, rule)
    creators = {u.id: u.username for u in db.scalars(select(User))}
    return render(request, "rule_detail.html", _ctx(
        db, rule=rule, versions=versions, shown=shown, creators=creators,
        rows=form_rows(shown.definition), definition=shown.definition, test=None, errors=[],
        name=rule.name, manufacturer_id=rule.manufacturer_id))


@router.post("/regeln/{rule_id}", dependencies=[Depends(check_csrf)])
async def update(request: Request, rule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return await _save(request, db, admin, _rule(db, rule_id))


@router.post("/regeln/{rule_id}/test", dependencies=[Depends(check_csrf)])
async def test_rule(request: Request, rule_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rule = _rule(db, rule_id)
    rv = current_version(db, rule)
    form = await request.form()
    errors = []
    amount = parse_amount(str(form.get("amount") or ""), ",")
    qty = parse_amount(str(form.get("quantity") or "1"), ",")
    if not amount.ok:
        errors.append(f"Betrag: {amount.message}")
    if not qty.ok or (qty.value is not None and qty.value <= 0):
        errors.append("Menge muss größer 0 sein")
    defn = RuleDefinition.model_validate(rv.definition)
    result = None
    if not errors:
        transport = parse_amount(str(form.get("transport") or ""), ",")
        result = calculate(defn, [PriceInput(defn.start_price, amount.value, "EUR",
                                             transport_cost=transport.value if transport.ok else None)], qty.value)
    versions = db.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule.id)
                          .order_by(RuleVersion.version.desc())).all()
    creators = {u.id: u.username for u in db.scalars(select(User))}
    return render(request, "rule_detail.html", _ctx(
        db, rule=rule, versions=versions, shown=rv, creators=creators, rows=form_rows(rv.definition),
        definition=rv.definition, test=result, errors=errors, name=rule.name, manufacturer_id=rule.manufacturer_id,
        test_input={"amount": form.get("amount"), "quantity": form.get("quantity"), "transport": form.get("transport")}))
