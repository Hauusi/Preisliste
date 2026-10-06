"""Kalkulation eines Herstellers über einen einfachen Faktor (VK = EK × Faktor) einrichten.

Die Standardregel heißt „<Hersteller> Standard“ und besteht aus genau einem Schritt „× Faktor“.
Ändert sich der Faktor, entsteht eine neue Regelversion (alte Ergebnisse bleiben nachvollziehbar).
Komplexere Regeln bleiben möglich (Seite Regeln); dann zeigt factor_of() None.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.calculations.engine import RuleDefinition
from backend.models.entities import Manufacturer, Rule, RuleVersion
from backend.services.rules import create_rule, current_version, new_version

DEFAULT_ROUNDING = {"mode": "HALF_UP", "places": 2, "timing": "STEP"}


def _simple_factor(definition: dict) -> Decimal | None:
    steps = definition.get("steps") or []
    if definition.get("start_price") == "EK" and len(steps) == 1 and steps[0].get("type") == "multiply":
        return Decimal(str(steps[0]["factor"]))
    return None


def factor_of(db: Session, m: Manufacturer | None) -> Decimal | None:
    """Faktor der Standardregel, wenn sie ein reiner EK-Faktor ist, sonst None."""
    rule = db.get(Rule, m.default_rule_id) if m and m.default_rule_id else None
    if rule is None or rule.deleted:
        return None
    return _simple_factor(current_version(db, rule).definition)


def set_factor(db: Session, m: Manufacturer, factor: Decimal, user) -> Rule:
    """Standardregel des Herstellers auf VK = EK × Faktor setzen (neu anlegen oder neue Version)."""
    if not Decimal(0) < factor <= Decimal(100):
        raise ValueError("Faktor muss größer 0 und höchstens 100 sein")
    rule = db.get(Rule, m.default_rule_id) if m.default_rule_id else None
    if rule is not None and not rule.deleted:
        rv = current_version(db, rule)
        if _simple_factor(rv.definition) == factor:
            return rule
        if _simple_factor(rv.definition) is not None:
            defn = RuleDefinition.model_validate({**rv.definition, "steps": [{"type": "multiply", "factor": str(factor)}]})
            new_version(db, rule, rule.name, m.id, defn, user, f"Faktor auf {factor} geändert")
            return rule
    defn = RuleDefinition.model_validate({"start_price": "EK", "rounding": DEFAULT_ROUNDING,
                                          "steps": [{"type": "multiply", "factor": str(factor)}]})
    name = f"{m.name} Standard"
    if db.scalar(select(Rule).where(Rule.name == name, Rule.owner_id == m.owner_id, Rule.deleted.is_(False))):
        name = f"{m.name} Standard ({factor})"
    rule = create_rule(db, name, m.id, defn, user, "Standardkalkulation des Herstellers", owner_id=m.owner_id)
    m.default_rule_id = rule.id
    db.flush()
    return rule
