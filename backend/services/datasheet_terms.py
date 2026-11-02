"""Wörterbuch für den Datenblatt-Import: Einträge des Admins laden und eingebaute Regeln zum Nachschlagen."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.entities import DatasheetTerm, Manufacturer
from backend.services import datasheet_import as dsi

KINDS = {
    "MERKMAL": "Merkmal (Zeilenname)",
    "WERT": "Wert / Wortlaut",
    "PRODUKTART": "Produktart",
}
HINTS = {
    "MERKMAL": "z. B. „Actual lumen“ → „Lichtleistung“. Standardzeilen: " + ", ".join(dsi.BB_ORDER)
               + "; jeder andere Name wird eine eigene Spezifikationszeile.",
    "WERT": "z. B. „Mag 70“ → „Magnetmontage“. Ersetzt den Ausdruck in Werten, Aufzählungen und Artikelbeschreibungen.",
    "PRODUKTART": "z. B. „work light“ → „Arbeitsscheinwerfer“ (Einzahl; Titel wird automatisch Mehrzahl).",
}


def load(db: Session, manufacturer: str | None) -> dict:
    """{Art: {Herstellerbegriff: B&B-Begriff}} – Einträge für alle Hersteller, darüber die des Herstellers."""
    terms: dict = {k: {} for k in KINDS}
    name = (manufacturer or "").strip().lower()
    rows = db.scalars(select(DatasheetTerm)).all()
    for row in sorted(rows, key=lambda r: bool(r.manufacturer)):  # herstellerbezogene zuletzt = gewinnen
        if row.kind in terms and (not row.manufacturer or row.manufacturer.lower() == name):
            terms[row.kind][row.source] = row.target
    return terms


def manufacturer_names(db: Session) -> list[str]:
    """Alle Herstellernamen (Benutzer haben eigene Hersteller; gleiche Namen zählen einmal)."""
    names = {m.name.strip() for m in db.scalars(select(Manufacturer))}
    names |= {r.manufacturer for r in db.scalars(select(DatasheetTerm)) if r.manufacturer}
    return sorted(names, key=str.lower)


def detect_manufacturer(text: str, manufacturers: list[Manufacturer]) -> Manufacturer | None:
    """Hersteller im PDF-Text finden (Name oder Alias als eigenes Wort, ab 3 Zeichen); häufigster gewinnt."""
    best, hits = None, 0
    for m in manufacturers:
        n = 0
        for name in [m.name, *(m.aliases or [])]:
            name = str(name or "").strip()
            if len(name) >= 3:
                n += len(re.findall(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I))
        if n > hits:
            best, hits = m, n
    return best


def builtin_rules() -> list[tuple[str, str, str]]:
    """Eingebaute Regeln zum Anzeigen: (Art, Herstellerbegriff, B&B-Begriff)."""
    out = []
    for name, words in dsi.PROPERTY_SYNONYMS.items():
        out += [("MERKMAL", w, name) for w in words if w != name.lower()]
    out += [("MERKMAL", en, de) for en, de in dsi.SPEC_DE.items()]
    out += [("WERT", example, re.sub(pattern, repl, example, flags=re.I)) for pattern, repl, example in dsi.VALUE_DE]
    out += [("PRODUKTART", en, de) for en, de in dsi.PRODUCT_TYPES_EN.items()]
    return out
