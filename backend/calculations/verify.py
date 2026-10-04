"""Gegenrechnung: rechnet eine Regel unabhängig von der Regelengine nach.

Bewusst eigener, einfacher Code (Rundung über ganze Zahlen statt Decimal.quantize), damit ein Fehler
in der Engine nicht unbemerkt bleibt. Unterstützt die für Hersteller-Kalkulationen üblichen Schritte.
Formeln, Staffeln und Mindestmengen werden nicht nachgerechnet (Ergebnis: nicht prüfbar).
"""

from __future__ import annotations

import math
from decimal import Decimal

from backend.calculations.engine import RuleDefinition

SUPPORTED = {"discount", "surcharge", "multiply", "fixed", "round", "round_ending"}


def _round_int(x: Decimal, mode: str) -> int:
    if mode == "UP":
        return math.ceil(x)
    if mode == "DOWN":
        return math.floor(x)
    sign = -1 if x < 0 else 1
    ax = abs(x)
    whole = math.floor(ax)
    frac = ax - whole
    half = Decimal("0.5")
    if frac > half:
        whole += 1
    elif frac == half and (mode == "HALF_UP" or whole % 2 == 1):
        whole += 1
    return sign * whole


def _round_places(x: Decimal, places: int, mode: str) -> Decimal:
    scale = Decimal(10) ** places
    return Decimal(_round_int(x * scale, mode)) / scale


def recalc(rule: RuleDefinition, start_value: Decimal) -> tuple[Decimal | None, str | None]:
    """(Ergebnis, None) oder (None, Grund, warum nicht nachrechenbar)."""
    unsupported = sorted({s.type for s in rule.steps} - SUPPORTED)
    if unsupported:
        return None, "Gegenrechnung nicht möglich für Schritt(e): " + ", ".join(unsupported)
    places, mode = rule.rounding.places, rule.rounding.mode
    per_step = rule.rounding.timing == "STEP"
    r = (lambda v: _round_places(v, places, mode)) if per_step else (lambda v: v)
    start = r(start_value)
    cur = start
    done: list[Decimal] = []
    for s in rule.steps:
        if s.type in ("discount", "surcharge"):
            base = start if s.base == "start" else cur if s.base == "current" else done[int(s.base[5:]) - 1]
            amount = r(base * s.percent / 100)
            cur = cur - amount if s.type == "discount" else cur + amount
        elif s.type == "multiply":
            cur = cur * s.factor
        elif s.type == "fixed":
            cur = cur + s.amount
        elif s.type == "round":
            cur = Decimal(_round_int(cur / s.increment, s.mode)) * s.increment
        elif s.type == "round_ending":
            n = math.floor((cur - s.ending) / s.period)
            low = n * s.period + s.ending
            high = low if low == cur else low + s.period
            if s.direction == "UP":
                cur = high
            elif s.direction == "DOWN":
                cur = low
            else:
                cur = high if high - cur <= cur - low else low
        cur = r(cur)
        if cur < 0:
            return None, "Ergebnis negativ"
        done.append(cur)
    return _round_places(cur, places, mode), None
