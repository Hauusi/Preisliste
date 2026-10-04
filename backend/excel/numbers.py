"""Beträge und Prozentwerte aus Excel-Zellen lesen. Ergebnis immer Decimal, nie float.

Grundsatz: nichts raten. Ist ein Wert mehrdeutig (z. B. "1.234": deutsch 1234, englisch 1,234),
wird er nur mit einem für die Spalte festgestellten Dezimaltrennzeichen aufgelöst, sonst UNKLAR.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

SUPPORTED_CURRENCIES = ("EUR", "USD", "CHF", "SEK", "NOK", "DKK", "GBP", "PLN", "CZK")

_CURRENCY_TOKENS = {
    "€": "EUR",
    "EUR": "EUR",
    "EURO": "EUR",
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "CHF": "CHF",
    "SFR": "CHF",
    "SFR.": "CHF",
    "FR.": "CHF",
    # Kronen nur mit Code: "kr" allein ist mehrdeutig (SEK, NOK, DKK) und wird nicht geraten
    "SEK": "SEK",
    "NOK": "NOK",
    "DKK": "DKK",
    "GBP": "GBP",
    "£": "GBP",
    "PLN": "PLN",
    "CZK": "CZK",
}

# Leerzeichen-Varianten und Apostroph (Schweiz) als Tausendertrennzeichen
_GROUP_CHARS = "    '’"
_NUMBER_RE = re.compile(r"^\d[\d.,]*$|^[.,]\d+$")


class PercentCell(Decimal):
    """Zahl aus einer Excel-Zelle mit Prozentformat, bereits mit 100 multipliziert (0.15 -> 15)."""


@dataclass(frozen=True)
class ParsedAmount:
    value: Decimal | None = None
    currency: str | None = None
    level: str | None = None  # FEHLER | UNKLAR, None = ok
    code: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.level is None and self.value is not None


def _err(level: str, code: str, message: str, currency: str | None = None) -> ParsedAmount:
    return ParsedAmount(level=level, code=code, message=message, currency=currency)


def is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _from_number(value) -> ParsedAmount:
    if isinstance(value, bool):
        return _err("FEHLER", "KEIN_BETRAG", "Wahrheitswert statt Betrag")
    if isinstance(value, int):
        return ParsedAmount(value=Decimal(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            return _err("FEHLER", "KEIN_BETRAG", "Ungültiger Zahlenwert")
        # repr liefert die kürzeste Darstellung, die Excel gespeichert hat (12.3 statt 12.2999...)
        return ParsedAmount(value=Decimal(repr(value)))
    if isinstance(value, Decimal):
        return ParsedAmount(value=value)
    return _err("FEHLER", "KEIN_BETRAG", f"Kein Betrag: {value!r}")


def _extract_currency(text: str) -> tuple[str, str | None, str | None]:
    """Gibt (Rest, Währung, unbekanntes Währungskürzel) zurück."""
    upper = text.upper()
    found = None
    for token in sorted(_CURRENCY_TOKENS, key=len, reverse=True):
        if token in upper:
            idx = upper.index(token)
            # Buchstaben-Tokens nur als ganzes Wort
            if token[0].isalpha():
                before = upper[idx - 1] if idx > 0 else " "
                after_idx = idx + len(token)
                after = upper[after_idx] if after_idx < len(upper) else " "
                if before.isalpha() or after.isalpha():
                    continue
            found = _CURRENCY_TOKENS[token]
            upper = upper[:idx] + " " + upper[idx + len(token):]
            break
    unknown = None
    if found is None:
        # Unbekanntes Kürzel nur, wenn der Rest eine Zahl ist ("12,50 GBP"), nicht bei Freitext
        m = re.fullmatch(r"\s*([A-Z]{3})?\s*([-+(]?[\d.,'\s\u00a0\u202f\u2009’]+[)-]?)\s*([A-Z]{3})?\s*", upper)
        if m and (m.group(1) or m.group(3)) and not (m.group(1) and m.group(3)):
            unknown = m.group(1) or m.group(3)
    return upper.strip(), found, unknown


def detect_separator(text: str) -> str | None:
    """Dezimaltrennzeichen, wenn eindeutig erkennbar, sonst None."""
    s = text.strip().lstrip("+-")
    for ch in _GROUP_CHARS:
        s = s.replace(ch, "")
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        return "," if s.rfind(",") > s.rfind(".") else "."
    for sep, other in ((",", "."), (".", ",")):
        if (has_comma if sep == "," else has_dot):
            parts = s.split(sep)
            if len(parts) > 2:
                return other  # mehrfach vorkommend => Tausendertrennzeichen
            if len(parts[1]) != 3:
                return sep  # 1,5 / 12,50 / 1.2345
            return None  # genau drei Ziffern: mehrdeutig
    return None


def _valid_grouping(int_part: str, group_sep: str) -> bool:
    if group_sep not in int_part:
        return True
    groups = int_part.split(group_sep)
    return 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])


def parse_amount(value, decimal_separator: str | None = None) -> ParsedAmount:
    """Betrag lesen. decimal_separator: ',' oder '.', falls für die Spalte festgestellt."""
    if is_empty(value):
        return _err("FEHLER", "LEER", "Kein Wert")
    if not isinstance(value, str):
        return _from_number(value)

    text = value.strip()
    rest, currency, unknown = _extract_currency(text)
    if unknown:
        return _err("FEHLER", "WAEHRUNG_UNBEKANNT", f"Unbekannte Währung: {unknown}")

    negative = False
    s = rest
    for ch in _GROUP_CHARS:
        s = s.replace(ch, "")
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = True, s[1:]
    elif s.endswith("-"):
        negative, s = True, s[:-1]
    elif s.startswith("+"):
        s = s[1:]

    if not _NUMBER_RE.match(s):
        return _err("FEHLER", "KEIN_BETRAG", f"Kein Betrag: {text!r}", currency)

    sep = detect_separator(s)
    if sep is None and ("." in s or "," in s):
        sep = decimal_separator
        if sep is None:
            return _err(
                "UNKLAR",
                "MEHRDEUTIG",
                f"Mehrdeutiger Wert {text!r}: Dezimal- oder Tausendertrennzeichen?",
                currency,
            )
    group = "." if sep == "," else ","
    if sep and s.count(sep) > 1:
        return _err("FEHLER", "KEIN_BETRAG", f"Mehrere Dezimaltrennzeichen: {text!r}", currency)
    if sep:
        int_part, _, frac = s.partition(sep)
    else:
        int_part, frac = s, ""
    if not _valid_grouping(int_part, group):
        return _err("FEHLER", "KEIN_BETRAG", f"Ungültige Zifferngruppierung: {text!r}", currency)
    int_part = int_part.replace(group, "")
    if group in frac or not (int_part or frac):
        return _err("FEHLER", "KEIN_BETRAG", f"Kein Betrag: {text!r}", currency)
    try:
        number = Decimal(f"{int_part or '0'}.{frac}" if frac else int_part)
    except InvalidOperation:
        return _err("FEHLER", "KEIN_BETRAG", f"Kein Betrag: {text!r}", currency)
    return ParsedAmount(value=-number if negative else number, currency=currency)


def parse_percent(value, decimal_separator: str | None = None) -> ParsedAmount:
    """Prozentwert lesen. "15 %", "15,5", 15 -> 15 bzw. 15.5.

    Excel-Zellen mit Prozentformat (0.15) kommen vom Reader als PercentCell(15).
    """
    if isinstance(value, PercentCell):
        return ParsedAmount(value=Decimal(value))
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        parsed = parse_amount(text, decimal_separator)
        if parsed.currency:
            return _err("FEHLER", "KEIN_PROZENTWERT", f"Währung in Prozentwert: {value!r}")
        return parsed
    return parse_amount(value, decimal_separator)


def detect_column_separator(values) -> str | None:
    """Dezimaltrennzeichen einer Spalte aus den eindeutigen Textwerten. None bei Widerspruch."""
    seen = set()
    for v in values:
        if isinstance(v, str) and v.strip():
            rest, _, _ = _extract_currency(v.strip())
            sep = detect_separator(rest)
            if sep:
                seen.add(sep)
    return seen.pop() if len(seen) == 1 else None
