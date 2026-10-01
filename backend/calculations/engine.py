"""Regelengine: geordnete Schritte, Decimal, konfigurierbare Rundung, vollständiger Rechenweg.

Jeder Schritt nennt seine Berechnungsbasis ausdrücklich:
  "start"   = Ausgangspreis
  "current" = Zwischenpreis vor diesem Schritt
  "step:N"  = Ergebnis von Schritt N (1-basiert, nur frühere Schritte)
Prozentschritte rechnen Prozent x Basis und verändern den Zwischenpreis um diesen Betrag.
Beispiel (Referenz): 100,00 - 15 % (Basis start) = 85,00; + 4 % (Basis current) = 88,40.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
)
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.calculations.formula import FormulaError, evaluate, parse

HUNDRED = Decimal(100)
ROUNDING_MODES = {
    "HALF_UP": ROUND_HALF_UP,  # kaufmännisch
    "HALF_EVEN": ROUND_HALF_EVEN,
    "UP": ROUND_CEILING,  # aufrunden (Richtung +unendlich)
    "DOWN": ROUND_FLOOR,  # abrunden (Richtung -unendlich)
}
MODE_LABELS = {"HALF_UP": "kaufmännisch", "HALF_EVEN": "mathematisch (Banker)", "UP": "aufrunden", "DOWN": "abrunden"}
PRICE_TYPES = ("LISTE", "EK", "UVP")
FORMULA_VARS = ("start", "current", "quantity", "transport", "discount")

class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=100)

class _BaseStep(_Step):
    base: str = "current"

    @field_validator("base")
    @classmethod
    def _base(cls, v):
        if v in ("start", "current"):
            return v
        if v.startswith("step:") and v[5:].isdigit() and int(v[5:]) >= 1:
            return v
        raise ValueError("Basis muss start, current oder step:N sein")

class DiscountStep(_BaseStep):
    type: Literal["discount"]
    percent: Decimal = Field(ge=0, le=100)

class SurchargeStep(_BaseStep):
    type: Literal["surcharge"]
    percent: Decimal = Field(ge=0, le=1000)

class FixedStep(_Step):
    type: Literal["fixed"]
    amount: Decimal  # negativ = Abzug

class TierStep(_Step):
    type: Literal["tier"]
    quantity: Decimal = Field(gt=0)

class MinQuantityStep(_Step):
    type: Literal["min_quantity"]
    quantity: Decimal = Field(gt=0)

class RoundStep(_Step):
    type: Literal["round"]
    increment: Decimal = Field(gt=0)
    mode: Literal["HALF_UP", "HALF_EVEN", "UP", "DOWN"] = "HALF_UP"

class RoundEndingStep(_Step):
    type: Literal["round_ending"]
    ending: Decimal = Field(ge=0)
    period: Decimal = Field(default=Decimal(1), gt=0)
    direction: Literal["UP", "DOWN", "NEAREST"] = "UP"

    @model_validator(mode="after")
    def _ending_lt_period(self):
        if self.ending >= self.period:
            raise ValueError("Endung muss kleiner als die Periode sein (z. B. 0,90 bei Periode 1,00)")
        return self

class FormulaStep(_Step):
    type: Literal["formula"]
    expression: str = Field(min_length=1, max_length=500)

Step = Annotated[
    Union[DiscountStep, SurchargeStep, FixedStep, TierStep, MinQuantityStep, RoundStep, RoundEndingStep, FormulaStep],
    Field(discriminator="type"),
]

class Rounding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["HALF_UP", "HALF_EVEN", "UP", "DOWN"] = "HALF_UP"
    places: int = Field(default=2, ge=0, le=6)
    timing: Literal["STEP", "END"] = "STEP"

class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_price: Literal["LISTE", "EK", "UVP"] = "LISTE"
    rounding: Rounding = Rounding()
    steps: list[Step] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _check_refs(self):
        names = set(FORMULA_VARS)
        for i, step in enumerate(self.steps, start=1):
            base = getattr(step, "base", None)
            if base and base.startswith("step:") and int(base[5:]) >= i:
                raise ValueError(f"Schritt {i}: Basis darf nur auf frühere Schritte verweisen")
            if isinstance(step, FormulaStep):
                try:
                    parse(step.expression, names)
                except FormulaError as exc:
                    raise ValueError(f"Schritt {i}: {exc}") from exc
            names.add(f"s{i}")
        return self

@dataclass
class PriceInput:
    price_type: str
    amount: Decimal
    currency: str
    min_quantity: Decimal | None = None
    discount_percent: Decimal | None = None
    transport_cost: Decimal | None = None

@dataclass
class CalcResult:
    status: str  # OK | FEHLER
    result: Decimal | None
    start: Decimal | None
    currency: str | None
    trace: list[dict] = field(default_factory=list)
    error: str | None = None

def quantize(value: Decimal, places: int, mode: str) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUNDING_MODES[mode])

def round_to_increment(value: Decimal, increment: Decimal, mode: str) -> Decimal:
    units = (value / increment).quantize(Decimal(1), rounding=ROUNDING_MODES[mode])
    return units * increment

def round_to_ending(value: Decimal, ending: Decimal, period: Decimal, direction: str) -> Decimal:
    k = ((value - ending) / period).to_integral_value(rounding=ROUND_FLOOR)
    lower = k * period + ending
    upper = lower if lower == value else lower + period
    if direction == "UP":
        return upper
    if direction == "DOWN":
        return lower
    return upper if (upper - value) <= (value - lower) else lower

def select_price(prices: list[PriceInput], price_type: str, quantity: Decimal) -> tuple[PriceInput | None, str | None]:
    """Preis des Typs für die Menge: Staffel mit größter Mindestmenge <= Menge."""
    candidates = [p for p in prices if p.price_type == price_type]
    if not candidates:
        return None, f"Kein Preis vom Typ {price_type} vorhanden"
    tiers = [p for p in candidates if p.min_quantity is not None]
    plain = [p for p in candidates if p.min_quantity is None]
    if tiers:
        eligible = [p for p in tiers if p.min_quantity <= quantity]
        if not eligible:
            return None, f"Keine Staffel für Menge {quantity} (kleinste Staffel ab {min(p.min_quantity for p in tiers)})"
        best = max(p.min_quantity for p in eligible)
        chosen = [p for p in eligible if p.min_quantity == best]
    else:
        chosen = plain
    if len(chosen) > 1:
        return None, f"Mehrere Preise vom Typ {price_type} für Menge {quantity}, nicht eindeutig"
    return chosen[0], None

def _fmt(d: Decimal) -> str:
    return format(d, "f")

def calculate(rule: RuleDefinition, prices: list[PriceInput], quantity: Decimal = Decimal(1)) -> CalcResult:
    r = rule.rounding
    step_round = r.timing == "STEP"

    def rnd(v: Decimal) -> Decimal:
        return quantize(v, r.places, r.mode) if step_round else v

    start_price, err = select_price(prices, rule.start_price, quantity)
    if err:
        return CalcResult("FEHLER", None, None, None, error=err)
    start = rnd(start_price.amount)
    currency = start_price.currency
    current = start
    results: list[Decimal] = []
    trace = [{"nr": 0, "typ": "start", "text": f"Ausgangspreis {rule.start_price}"
              + (f" (Staffel ab {_fmt(start_price.min_quantity)})" if start_price.min_quantity is not None else ""),
              "ergebnis": _fmt(start)}]

    def fail(i, msg):
        return CalcResult("FEHLER", None, start, currency, trace, f"Schritt {i}: {msg}")

    for i, step in enumerate(rule.steps, start=1):
        entry: dict = {"nr": i, "typ": step.type, "text": step.label or ""}
        before = current
        if isinstance(step, (DiscountStep, SurchargeStep)):
            if step.base == "start":
                base_value = start
            elif step.base == "current":
                base_value = current
            else:
                base_value = results[int(step.base[5:]) - 1]
            delta = rnd(base_value * step.percent / HUNDRED)
            current = current - delta if isinstance(step, DiscountStep) else current + delta
            sign = "-" if isinstance(step, DiscountStep) else "+"
            entry.update(basis=step.base, basis_wert=_fmt(base_value), operand=f"{sign}{_fmt(step.percent)} %",
                         betrag=_fmt(delta))
        elif isinstance(step, FixedStep):
            current = current + step.amount
            entry.update(operand=("+" if step.amount >= 0 else "") + _fmt(step.amount))
        elif isinstance(step, TierStep):
            tier, terr = select_price(prices, rule.start_price, step.quantity)
            if terr:
                return fail(i, terr)
            if tier.currency != currency:
                return fail(i, "Staffelpreis in anderer Währung")
            current = tier.amount
            entry.update(operand=f"Staffelpreis für Menge {_fmt(step.quantity)}")
        elif isinstance(step, MinQuantityStep):
            if quantity < step.quantity:
                return fail(i, f"Mindestmenge {_fmt(step.quantity)} nicht erreicht (Menge {_fmt(quantity)})")
            entry.update(operand=f"Mindestmenge {_fmt(step.quantity)} erfüllt")
        elif isinstance(step, RoundStep):
            current = round_to_increment(current, step.increment, step.mode)
            entry.update(operand=f"auf {_fmt(step.increment)} {MODE_LABELS[step.mode]}")
        elif isinstance(step, RoundEndingStep):
            current = round_to_ending(current, step.ending, step.period, step.direction)
            entry.update(operand=f"auf Endung {_fmt(step.ending)} ({step.direction})")
        elif isinstance(step, FormulaStep):
            variables = {
                "start": start, "current": current, "quantity": quantity,
                "transport": start_price.transport_cost, "discount": start_price.discount_percent,
                **{f"s{n}": v for n, v in enumerate(results, start=1)},
            }
            try:
                current = evaluate(step.expression, variables)
            except FormulaError as exc:
                return fail(i, str(exc))
            entry.update(operand=step.expression)
        current = rnd(current)
        if current < 0:
            return fail(i, f"Ergebnis negativ ({_fmt(current)})")
        entry.update(vorher=_fmt(before), ergebnis=_fmt(current))
        results.append(current)
        trace.append(entry)

    final = quantize(current, r.places, r.mode)
    if not step_round:
        trace.append({"nr": len(rule.steps) + 1, "typ": "rundung_ende",
                      "text": f"Rundung am Ende auf {r.places} Stellen ({MODE_LABELS[r.mode]})",
                      "vorher": _fmt(current), "ergebnis": _fmt(final)})
    return CalcResult("OK", final, start, currency, trace)
