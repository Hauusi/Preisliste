from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.calculations.engine import PriceInput, RuleDefinition, calculate, round_to_ending, round_to_increment
from backend.calculations.formula import FormulaError, evaluate

D = Decimal


def rule(steps, **kw):
    return RuleDefinition.model_validate({"steps": steps, **kw})


def price(amount, typ="LISTE", qty=None, cur="EUR", transport=None):
    return PriceInput(typ, D(amount), cur, D(qty) if qty is not None else None, transport_cost=transport)


def test_reference_example():
    r = rule([{"type": "discount", "percent": "15", "base": "start"},
              {"type": "surcharge", "percent": "4", "base": "current"}])
    res = calculate(r, [price("100.00")])
    assert res.status == "OK" and res.result == D("88.40")
    assert [t["ergebnis"] for t in res.trace] == ["100.00", "85.00", "88.40"]
    assert res.trace[2]["betrag"] == "3.40" and res.trace[2]["basis_wert"] == "85.00"


def test_base_start_vs_current():
    steps = lambda base: [{"type": "discount", "percent": "15", "base": "start"},
                          {"type": "surcharge", "percent": "4", "base": base}]
    assert calculate(rule(steps("start")), [price("100")]).result == D("89.00")
    assert calculate(rule(steps("step:1")), [price("100")]).result == D("88.40")


def test_fixed_amount():
    r = rule([{"type": "fixed", "amount": "3.40"}, {"type": "fixed", "amount": "-1.00"}])
    assert calculate(r, [price("10.00")]).result == D("12.40")


def test_half_up_edge_cases():
    r = rule([{"type": "discount", "percent": "50", "base": "start"}])
    # Pro Schritt wird der Rabattbetrag gerundet: 0,005 -> 0,01, Preis 0,01 - 0,01 = 0,00
    assert calculate(r, [price("0.01")]).result == D("0.00")
    assert calculate(r, [price("2.25")]).result == D("1.12")  # Rabatt 1,125 -> 1,13
    r_even = rule([{"type": "discount", "percent": "50", "base": "start"}], rounding={"mode": "HALF_EVEN"})
    assert calculate(r_even, [price("2.25")]).result == D("1.13")  # Rabatt 1,125 -> 1,12
    r_end = rule([{"type": "discount", "percent": "50", "base": "start"}], rounding={"timing": "END"})
    assert calculate(r_end, [price("2.25")]).result == D("1.13")  # 1,125 -> 1,13


def test_step_rounding_differs_from_end_rounding():
    steps = [{"type": "discount", "percent": "50", "base": "current"},
             {"type": "discount", "percent": "50", "base": "current"}]
    # 0,30 -> 0,15 -> Rabatt 0,075: pro Schritt 0,08 (0,15 - 0,08 = 0,07), am Ende 0,075 -> 0,08
    step = calculate(rule(steps), [price("0.30")])
    end = calculate(rule(steps, rounding={"timing": "END"}), [price("0.30")])
    assert step.result == D("0.07")  # 0,15 - round(0,075)=0,08 -> 0,07
    assert end.result == D("0.08")   # 0,075 -> 0,08
    assert end.trace[-1]["typ"] == "rundung_ende"


def test_tier_selection_by_quantity():
    prices = [price("10.00", qty=1), price("9.00", qty=10), price("8.00", qty=100)]
    r = rule([{"type": "fixed", "amount": "0"}])
    assert calculate(r, prices, D(1)).result == D("10.00")
    assert calculate(r, prices, D(50)).result == D("9.00")
    assert calculate(r, prices, D(100)).result == D("8.00")
    tier = rule([{"type": "tier", "quantity": "100"}])
    assert calculate(tier, prices, D(1)).result == D("8.00")
    res = calculate(r, [price("9.00", qty=10)], D(5))
    assert res.status == "FEHLER" and "Staffel" in res.error


def test_min_quantity():
    r = rule([{"type": "min_quantity", "quantity": "10"}])
    assert calculate(r, [price("1")], D(10)).status == "OK"
    res = calculate(r, [price("1")], D(5))
    assert res.status == "FEHLER" and "Mindestmenge" in res.error


def test_rounding_steps():
    assert round_to_increment(D("12.32"), D("0.05"), "HALF_UP") == D("12.30")
    assert round_to_increment(D("12.33"), D("0.05"), "HALF_UP") == D("12.35")
    assert round_to_increment(D("12.01"), D("1"), "UP") == D("13")
    assert round_to_ending(D("12.34"), D("0.90"), D(1), "UP") == D("12.90")
    assert round_to_ending(D("12.95"), D("0.90"), D(1), "UP") == D("13.90")
    assert round_to_ending(D("12.90"), D("0.90"), D(1), "UP") == D("12.90")
    assert round_to_ending(D("12.34"), D("0.90"), D(1), "DOWN") == D("11.90")
    assert round_to_ending(D("12.34"), D("0.99"), D(1), "NEAREST") == D("11.99")
    assert round_to_ending(D("12.60"), D("0.99"), D(1), "NEAREST") == D("12.99")
    r = rule([{"type": "round_ending", "ending": "0.90"}])
    assert calculate(r, [price("12.34")]).result == D("12.90")


def test_formula_step_and_variables():
    r = rule([{"type": "discount", "percent": "10", "base": "start"},
              {"type": "formula", "expression": "s1 * 1.19 + transport"}])
    res = calculate(r, [price("100.00", transport=D("5.00"))])
    assert res.result == D("112.10")  # 90 * 1,19 = 107,10 + 5
    res = calculate(r, [price("100.00")])
    assert res.status == "FEHLER" and "transport" in res.error


@pytest.mark.parametrize("expr", [
    "__import__('os')", "open('x')", "start.__class__", "start ** 2", "[1,2]", "lambda: 1",
    "start if start else 1", "unbekannt + 1", "max(start)", "'text'",
])
def test_formula_rejects_unsafe(expr):
    with pytest.raises(FormulaError):
        evaluate(expr, {"start": D(1)})


def test_formula_decimal_exact_and_division_by_zero():
    assert evaluate("0.1 + 0.2", {}) == D("0.3")
    assert evaluate("max(start, 5) / 2", {"start": D(3)}) == D("2.5")
    with pytest.raises(FormulaError):
        evaluate("start / 0", {"start": D(1)})


def test_rule_validation():
    with pytest.raises(ValidationError):
        rule([{"type": "discount", "percent": "150"}])
    with pytest.raises(ValidationError):
        rule([{"type": "discount", "percent": "10", "base": "step:1"}])  # Verweis auf sich selbst
    with pytest.raises(ValidationError):
        rule([{"type": "formula", "expression": "s2 + 1"}])  # späterer Schritt
    with pytest.raises(ValidationError):
        rule([{"type": "unbekannt"}])
    with pytest.raises(ValidationError):
        rule([])


def test_missing_price_type_and_negative_result():
    r = rule([{"type": "fixed", "amount": "-5"}], start_price="EK")
    assert calculate(r, [price("1")]).status == "FEHLER"
    res = calculate(r, [price("1", typ="EK")])
    assert res.status == "FEHLER" and "negativ" in res.error


def test_percent_change_example_precision():
    r = rule([{"type": "discount", "percent": "33.333", "base": "start"}])
    assert calculate(r, [price("99.99")]).result == D("66.66")  # 33,33 Rabatt (33,3297 -> 33,33)


def test_multiply_step_and_german_formula():
    r = rule([{"type": "multiply", "factor": "2.6"}], start_price="EK")
    res = calculate(r, [price("10.00", typ="EK")])
    assert res.result == D("26.00") and res.trace[1]["operand"] == "× 2.6"
    assert evaluate("current * 2,6", {"current": D("10")}) == D("26.0")
    assert evaluate("max(start; 5,5)", {"start": D("3")}) == D("5.5")
    with pytest.raises(FormulaError, match="vollständig"):
        evaluate("* 2,6", {"current": D("10")})
