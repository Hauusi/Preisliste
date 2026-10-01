from decimal import Decimal

import pytest

from backend.excel.numbers import PercentCell, detect_column_separator, parse_amount, parse_percent

D = Decimal


@pytest.mark.parametrize("text,expected,currency", [
    ("1.234,56 €", D("1234.56"), "EUR"),
    ("1234,56", D("1234.56"), None),
    ("12,5", D("12.5"), None),
    ("0,99", D("0.99"), None),
    ("EUR 1.234.567,89", D("1234567.89"), "EUR"),
    ("1,234.56", D("1234.56"), None),
    ("1 234,56 €", D("1234.56"), "EUR"),
    ("1 234,56", D("1234.56"), None),
    ("CHF 1'234.50", D("1234.50"), "CHF"),
    ("$12.99", D("12.99"), "USD"),
    ("12.99 USD", D("12.99"), "USD"),
    ("-12,50", D("-12.50"), None),
    ("12,50-", D("-12.50"), None),
    ("(12,50)", D("-12.50"), None),
    ("100", D("100"), None),
    ("1.234.567", D("1234567"), None),
    ("1,234,567", D("1234567"), None),
])
def test_german_and_other_formats(text, expected, currency):
    p = parse_amount(text)
    assert p.ok, p
    assert p.value == expected
    assert p.currency == currency


def test_numbers_from_excel_are_decimal_not_float():
    p = parse_amount(12.3)
    assert p.value == D("12.3") and isinstance(p.value, Decimal)
    assert parse_amount(0.1).value == D("0.1")
    assert parse_amount(7).value == D(7)


@pytest.mark.parametrize("text", ["1.234", "1,234", "12.500 €"])
def test_ambiguous_without_column_hint_is_unclear(text):
    p = parse_amount(text)
    assert not p.ok
    assert p.level == "UNKLAR" and p.code == "MEHRDEUTIG"


def test_ambiguous_resolved_by_column_separator():
    assert parse_amount("1.234", ",").value == D("1234")
    assert parse_amount("1.234", ".").value == D("1.234")
    assert parse_amount("1,234", ",").value == D("1.234")


@pytest.mark.parametrize("text,code", [
    ("12,50 GBP", "WAEHRUNG_UNBEKANNT"),
    ("auf Anfrage", "KEIN_BETRAG"),
    ("12,5,0", "KEIN_BETRAG"),
    ("1.23.4,5", "KEIN_BETRAG"),
    ("", "LEER"),
    (None, "LEER"),
    (True, "KEIN_BETRAG"),
    (float("nan"), "KEIN_BETRAG"),
])
def test_invalid_values_are_errors(text, code):
    p = parse_amount(text)
    assert not p.ok
    assert p.level == "FEHLER" and p.code == code


def test_percent():
    assert parse_percent("15 %").value == D("15")
    assert parse_percent("15,5%").value == D("15.5")
    assert parse_percent(PercentCell(D("15"))).value == D("15")
    assert not parse_percent("15 €").ok


def test_column_separator_detection():
    assert detect_column_separator(["12,50", "1.234,00", "1.234"]) == ","
    assert detect_column_separator(["12.50", "1,234.00"]) == "."
    assert detect_column_separator(["12,50", "12.50"]) is None
    assert detect_column_separator(["1.234"]) is None
