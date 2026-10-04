"""Kopfzeilen- und Spaltenerkennung: 1. Synonymliste, 2. Heuristik. KI-Fallback folgt in Gruppe C.

Ergebnis ist immer nur ein Vorschlag; der Benutzer bestätigt die Zuordnung in der Vorschau.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from backend.excel.numbers import detect_column_separator, is_empty, parse_amount
from backend.excel.reader import SheetData

FIELDS: dict[str, str] = {
    "article_number": "Artikelnummer",
    "manufacturer": "Hersteller",
    "description": "Bezeichnung",
    "category": "Kategorie / Serie",
    "supplier_price": "Einkaufspreis (EK)",
    "list_price": "VK / Listenpreis",
    "rrp": "UVP",
    "discount": "Rabatt %",
    "transport_cost": "Transportkosten",
    "quantity": "Menge / Staffel ab",
    "unit": "Einheit",
    "currency": "Währung",
    "valid_from": "Gültig ab",
}
PRICE_FIELDS = ("supplier_price", "list_price", "rrp")
HEADER_SCAN_ROWS = 30


def normalize_label(text: str) -> str:
    text = str(text).strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(t for t in re.split(r"[^a-z0-9]+", normalize_label(text)) if t)


def _compact(text: str) -> str:
    return "".join(_tokens(text))


@lru_cache
def _load_synonyms(path: str) -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    unknown = set(data) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unbekannte Felder in {path}: {sorted(unknown)}")
    return {k: [str(s) for s in v] for k, v in data.items()}


def load_synonyms(config_dir: Path) -> dict[str, list[str]]:
    return _load_synonyms(str(config_dir / "header_synonyms.yaml"))


def match_label(label: str, synonyms: dict[str, list[str]]) -> list[tuple[str, float]]:
    """Kandidaten (Feld, Score) für eine Überschrift. 1.0 = exakt, 0.7 = Wortübereinstimmung."""
    if is_empty(label):
        return []
    compact = _compact(label)
    tokens = set(_tokens(label))
    best: dict[str, float] = {}
    for fld, syns in synonyms.items():
        for syn in syns:
            if _compact(syn) == compact:
                best[fld] = 1.0
                break
            syn_tokens = set(_tokens(syn))
            if syn_tokens and syn_tokens <= tokens:
                best[fld] = max(best.get(fld, 0), 0.7)
    return sorted(best.items(), key=lambda kv: -kv[1])


@dataclass
class ColumnGuess:
    index: int  # 0-basiert
    label: str
    field: str | None
    score: float
    source: str  # synonym | heuristik | keine
    note: str | None = None


@dataclass
class Detection:
    header_row: int  # 1-basiert (Excel-Zeile); bei zweizeiliger Kopfzeile die untere
    header_rows: int
    columns: list[ColumnGuess]
    decimal_separators: dict[int, str | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def mapping(self) -> dict[str, int]:
        return {c.field: c.index for c in self.columns if c.field}


def _fill_merged(sheet: SheetData, rows: list[list]) -> list[list]:
    """Werte verbundener Zellen auf alle Zellen des Bereichs übertragen (nur für Kopfzeilen)."""
    filled = [list(r) for r in rows]
    for min_r, min_c, max_r, max_c in sheet.merged:
        if min_r - 1 >= len(filled):
            continue
        top = filled[min_r - 1]
        value = top[min_c - 1] if min_c - 1 < len(top) else None
        for r in range(min_r, min(max_r, len(filled)) + 1):
            row = filled[r - 1]
            while len(row) < max_c:
                row.append(None)
            for c in range(min_c, max_c + 1):
                row[c - 1] = value
    return filled


def _row_score(row: list, synonyms) -> tuple[int, int]:
    hits = sum(1 for v in row if isinstance(v, str) and match_label(v, synonyms))
    texts = sum(1 for v in row if isinstance(v, str) and v.strip())
    return hits, texts


def find_header_row(sheet: SheetData, synonyms) -> tuple[int | None, int]:
    """(Kopfzeile 1-basiert, Anzahl Kopfzeilen). None, wenn keine plausible Zeile gefunden."""
    scan = _fill_merged(sheet, sheet.rows[:HEADER_SCAN_ROWS])
    best_idx, best = None, (0, 0)
    for idx, row in enumerate(scan):
        score = _row_score(row, synonyms)
        if score > best:
            best_idx, best = idx, score
    if best_idx is None or best[0] < 2:
        # Heuristik: erste Zeile mit >= 3 Textzellen, auf die eine Zeile mit Zahlen folgt
        for idx, row in enumerate(scan[:-1]):
            texts = sum(1 for v in row if isinstance(v, str) and v.strip())
            own_nums = sum(1 for v in row if not is_empty(v) and parse_amount(v).ok)
            nums = sum(1 for v in scan[idx + 1] if not is_empty(v) and parse_amount(v).ok)
            if texts >= 3 and own_nums == 0 and nums >= 1:
                return idx + 1, 1
        return None, 1
    # Zweizeilige Kopfzeile: darüberliegende Zeile mit verbundenen Zellen über der Kopfzeile
    if best_idx > 0:
        above = best_idx  # 1-basiert die Zeile darüber
        merged_above = any(
            min_r == above and max_c > min_c for (min_r, min_c, _max_r, max_c) in sheet.merged
        )
        if merged_above:
            return best_idx + 1, 2
    return best_idx + 1, 1


def header_labels(sheet: SheetData, header_row: int, header_rows: int) -> list[str]:
    rows = _fill_merged(sheet, sheet.rows[: header_row])
    lower = rows[header_row - 1]
    upper = rows[header_row - 2] if header_rows == 2 and header_row >= 2 else []
    width = max(len(lower), len(upper))
    labels = []
    for i in range(width):
        lo = lower[i] if i < len(lower) else None
        up = upper[i] if i < len(upper) else None
        parts = [str(p).strip() for p in (up, lo) if not is_empty(p)]
        # Gleiche Werte (verbundene Zelle über beide Zeilen) nicht doppeln
        if len(parts) == 2 and parts[0] == parts[1]:
            parts = parts[:1]
        labels.append(" ".join(parts))
    return labels


def _column_values(sheet: SheetData, header_row: int, index: int, limit: int = 500) -> list:
    values = []
    for row in sheet.rows[header_row: header_row + limit]:
        v = row[index] if index < len(row) else None
        if not is_empty(v):
            values.append(v)
    return values


def _looks_like_article_number(values: list) -> bool:
    if len(values) < 3:
        return False
    strs = [str(v).strip() for v in values]
    unique_ratio = len(set(strs)) / len(strs)
    pattern = sum(1 for s in strs if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-/_]{1,39}", s)) / len(strs)
    has_digit = sum(1 for s in strs if any(ch.isdigit() for ch in s)) / len(strs)
    return unique_ratio >= 0.95 and pattern >= 0.95 and has_digit >= 0.9


def _price_ratio(values: list) -> float:
    if not values:
        return 0.0
    sep = detect_column_separator(values)
    ok = sum(1 for v in values if parse_amount(v, sep).ok)
    return ok / len(values)


def detect_columns(
    sheet: SheetData, synonyms, header_row: int | None = None, header_rows: int | None = None
) -> Detection:
    notes: list[str] = []
    if header_row is None:
        header_row, header_rows = find_header_row(sheet, synonyms)
        if header_row is None:
            return Detection(header_row=1, header_rows=1, columns=[], notes=[
                "Keine Kopfzeile erkannt. Bitte Kopfzeile manuell angeben."
            ])
    header_rows = header_rows or 1
    labels = header_labels(sheet, header_row, header_rows)

    guesses: list[ColumnGuess] = []
    claimed: dict[str, ColumnGuess] = {}
    for i, label in enumerate(labels):
        candidates = match_label(label, synonyms)
        if not candidates and header_rows == 2:
            # untere Zeile allein prüfen
            lower = sheet.rows[header_row - 1]
            lo = lower[i] if i < len(lower) else None
            candidates = match_label(lo, synonyms) if not is_empty(lo) else []
        guess = ColumnGuess(index=i, label=label, field=None, score=0.0, source="keine")
        if candidates:
            top_field, top_score = candidates[0]
            ties = [f for f, s in candidates if s == top_score]
            if len(ties) > 1:
                names = ", ".join(FIELDS[f] for f in ties)
                guess.note = f"Mehrdeutige Überschrift ({names}), bitte zuordnen"
            else:
                guess.field, guess.score, guess.source = top_field, top_score, "synonym"
        guesses.append(guess)

    # Doppelte Zuordnung: höchster Score gewinnt, bei Gleichstand keine Übernahme
    by_field: dict[str, list[ColumnGuess]] = {}
    for g in guesses:
        if g.field:
            by_field.setdefault(g.field, []).append(g)
    for fld, group in by_field.items():
        top = max(g.score for g in group)
        winners = [g for g in group if g.score == top]
        if len(winners) == 1:
            claimed[fld] = winners[0]
        for g in group:
            if len(winners) == 1 and g is winners[0]:
                continue
            g.field, g.source = None, "keine"
            if len(winners) == 1:
                g.note = f"Auch als {FIELDS[fld]} erkannt, Spalte {winners[0].index + 1} passt besser"
            else:
                g.note = f"{FIELDS[fld]} in mehreren Spalten erkannt, bitte zuordnen"

    # Heuristik nur für Pflichtfelder, die nicht über Synonyme gefunden wurden
    free = [g for g in guesses if g.field is None and not g.note]
    if "article_number" not in claimed:
        for g in free:
            if _looks_like_article_number(_column_values(sheet, header_row, g.index)):
                g.field, g.score, g.source = "article_number", 0.5, "heuristik"
                claimed["article_number"] = g
                free.remove(g)
                break
    if not any(f in claimed for f in PRICE_FIELDS):
        candidates = [
            (g, _price_ratio(_column_values(sheet, header_row, g.index))) for g in free
        ]
        candidates = [c for c in candidates if c[1] >= 0.9]
        if len(candidates) == 1:
            g = candidates[0][0]
            g.field, g.score, g.source = "list_price", 0.5, "heuristik"
            g.note = "Als Preis erkannt; ob EK, Listenpreis oder UVP, bitte prüfen"
            claimed["list_price"] = g
        elif len(candidates) > 1:
            notes.append("Mehrere Spalten sehen wie Preise aus. Bitte Preisspalten zuordnen.")

    if "article_number" not in claimed:
        notes.append("Artikelnummer-Spalte nicht automatisch erkannt, bitte unten zuordnen.")
    if not any(f in claimed for f in PRICE_FIELDS):
        notes.append("Preisspalte nicht automatisch erkannt, bitte unten zuordnen.")

    seps = {}
    for g in guesses:
        if g.field in PRICE_FIELDS + ("discount", "transport_cost", "quantity"):
            seps[g.index] = detect_column_separator(_column_values(sheet, header_row, g.index, 5000))

    return Detection(
        header_row=header_row, header_rows=header_rows, columns=guesses,
        decimal_separators=seps, notes=notes,
    )


def suggest_manufacturer(
    known: list[tuple[int, str, list[str]]], file_name: str, sheet: SheetData, header_row: int
) -> int | None:
    """Herstellervorschlag aus Dateiname, Blattname und Zeilen über der Kopfzeile."""
    haystack = " ".join(
        [file_name, sheet.name]
        + [str(v) for row in sheet.rows[: max(header_row - 1, 0)] for v in row if v is not None]
    )
    hay_tokens = set(_tokens(haystack))
    hay_compact = _compact(haystack)
    hits = []
    for mid, name, aliases in known:
        for candidate in [name, *aliases]:
            tok = set(_tokens(candidate))
            if not tok:
                continue
            if tok <= hay_tokens or (len(_compact(candidate)) >= 5 and _compact(candidate) in hay_compact):
                hits.append(mid)
                break
    return hits[0] if len(set(hits)) == 1 else None
