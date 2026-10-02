"""Hersteller: Kürzel prüfen, Anzeige der Artikelnummer mit Kürzel."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.entities import Manufacturer

CODE_RE = re.compile(r"[A-Z0-9]{1,10}")


def normalize_code(raw: str | None) -> str | None:
    code = (raw or "").strip().upper()
    return code or None


def validate_code(db: Session, code: str | None, exclude_id: int | None = None) -> str | None:
    """Fehlertext oder None. Kürzel: 1-10 Zeichen, nur A-Z und 0-9, eindeutig."""
    if code is None:
        return None
    if not CODE_RE.fullmatch(code):
        return "Kürzel: 1 bis 10 Zeichen, nur Buchstaben A-Z und Ziffern"
    other = db.scalar(select(Manufacturer).where(Manufacturer.code == code))
    if other and other.id != exclude_id:
        return f"Kürzel {code} ist schon an {other.name} vergeben"
    return None


def code_map(db: Session) -> dict[int, str]:
    return {m.id: m.code for m in db.scalars(select(Manufacturer).where(Manufacturer.code.is_not(None)))}


def with_code(number: str | None, code: str | None) -> str | None:
    """Firmenkürzel direkt vor die Artikelnummer: RA + LED1 = RALED1."""
    return f"{code}{number}" if number and code else number


def suggest_by_code(db: Session, numbers: list) -> int | None:
    """Hersteller, wenn mindestens 80 % der Artikelnummern mit seinem Kürzel beginnen (eindeutig)."""
    values = [str(n).strip().upper() for n in numbers if n not in (None, "")]
    if not values:
        return None
    hits = []
    for mid, code in code_map(db).items():
        share = sum(1 for v in values if v.startswith(code)) / len(values)
        if share >= 0.8:
            hits.append((len(code), mid))
    if not hits:
        return None
    hits.sort(reverse=True)  # längstes passendes Kürzel gewinnt (RAX vor RA)
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return None
    return hits[0][1]


def search_conditions(db: Session, q: str, number_col, manufacturer_col) -> list:
    """Zusatzbedingungen, damit die Suche nach RT12345 Artikel 12345 von Hersteller RT findet."""
    q = q.strip().upper()
    conds = []
    for mid, code in code_map(db).items():
        if q.startswith(code) and len(q) > len(code):
            conds.append((manufacturer_col == mid) & number_col.ilike(f"%{q[len(code):]}%"))
    return conds
