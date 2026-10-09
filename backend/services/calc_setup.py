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

# VK-Rundung nach dem Faktor (Preisoptik). Endungen runden immer AUF, damit die Marge nie sinkt.
VK_ROUNDINGS = {
    "": ("keine (auf Cent)", None),
    "0.10": ("auf 10 Cent", {"type": "round", "increment": "0.10", "mode": "HALF_UP"}),
    "0.10up": ("auf 10 Cent (aufrunden)", {"type": "round", "increment": "0.10", "mode": "UP"}),
    "1": ("auf volle Euro", {"type": "round", "increment": "1", "mode": "HALF_UP"}),
    "e90": ("auf ,90 (aufrunden)", {"type": "round_ending", "ending": "0.90", "period": "1", "direction": "UP"}),
    "e95": ("auf ,95 (aufrunden)", {"type": "round_ending", "ending": "0.95", "period": "1", "direction": "UP"}),
    "e99": ("auf ,99 (aufrunden)", {"type": "round_ending", "ending": "0.99", "period": "1", "direction": "UP"}),
}


def _rounding_key(step: dict | None) -> str | None:
    if step is None:
        return ""
    for key, (_, spec) in VK_ROUNDINGS.items():
        if spec and spec["type"] == step.get("type") and all(
                Decimal(str(step.get(k))) == Decimal(v) if k in ("increment", "ending", "period") else step.get(k) == v
                for k, v in spec.items() if k != "type"):
            return key
    return None


def describe(factor: Decimal | None, rounding: str | None) -> str:
    """Kurztext für Anzeige: 'EK × 2,6, auf ,90 (aufrunden)'."""
    from backend.comparison.update import de

    if factor is None:
        return ""
    text = f"EK × {de(factor, 0)}"
    return f"{text}, {VK_ROUNDINGS[rounding][0]}" if rounding else text


def _parse(definition: dict) -> tuple[Decimal, str] | None:
    """(Faktor, Rundungsschlüssel) für Regeln der Form 'EK × Faktor [+ VK-Rundung]', sonst None."""
    steps = definition.get("steps") or []
    if definition.get("start_price") != "EK" or not steps or steps[0].get("type") != "multiply" or len(steps) > 2:
        return None
    key = _rounding_key(steps[1] if len(steps) == 2 else None)
    return (Decimal(str(steps[0]["factor"])), key) if key is not None else None


def _simple_factor(definition: dict) -> Decimal | None:
    parsed = _parse(definition)
    return parsed[0] if parsed else None


def rounding_of(db: Session, m: Manufacturer | None) -> str:
    rule = db.get(Rule, m.default_rule_id) if m and m.default_rule_id else None
    if rule is None or rule.deleted:
        return ""
    parsed = _parse(current_version(db, rule).definition)
    return parsed[1] if parsed else ""


def factor_of(db: Session, m: Manufacturer | None) -> Decimal | None:
    """Faktor der Standardregel, wenn sie ein reiner EK-Faktor ist, sonst None."""
    rule = db.get(Rule, m.default_rule_id) if m and m.default_rule_id else None
    if rule is None or rule.deleted:
        return None
    return _simple_factor(current_version(db, rule).definition)


def set_factor(db: Session, m: Manufacturer, factor: Decimal, user, rounding: str | None = None) -> Rule:
    """Standardregel des Herstellers auf VK = EK × Faktor [+ VK-Rundung] setzen (neu oder neue Version).
    rounding=None behält die bisherige Rundung."""
    if not Decimal(0) < factor <= Decimal(100):
        raise ValueError("Faktor muss größer 0 und höchstens 100 sein")
    if rounding is not None and rounding not in VK_ROUNDINGS:
        raise ValueError("Unbekannte Rundung")
    rule = db.get(Rule, m.default_rule_id) if m.default_rule_id else None
    current = _parse(current_version(db, rule).definition) if rule is not None and not rule.deleted else None
    if rounding is None:
        rounding = current[1] if current else ""
    steps = [{"type": "multiply", "factor": str(factor)}] + ([VK_ROUNDINGS[rounding][1]] if rounding else [])
    if current is not None:
        if current == (factor, rounding):
            return rule
        rv = current_version(db, rule)
        defn = RuleDefinition.model_validate({**rv.definition, "steps": steps})
        new_version(db, rule, rule.name, m.id, defn, user, f"Kalkulation geändert: {describe(factor, rounding)}")
        return rule
    defn = RuleDefinition.model_validate({"start_price": "EK", "rounding": DEFAULT_ROUNDING, "steps": steps})
    name = f"{m.name} Standard"
    if db.scalar(select(Rule).where(Rule.name == name, Rule.owner_id == m.owner_id, Rule.deleted.is_(False))):
        name = f"{m.name} Standard ({factor})"
    rule = create_rule(db, name, m.id, defn, user, "Standardkalkulation des Herstellers", owner_id=m.owner_id)
    m.default_rule_id = rule.id
    db.flush()
    return rule
