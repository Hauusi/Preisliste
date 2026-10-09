"""Sichtbarkeit pro Benutzer: jeder sieht nur seine eigenen Inhalte, Administratoren sehen alles.

Eigentümer-Spalte je Tabelle; abhängige Daten (Artikel, Ergebnisse, Ausnahmen, Zuordnungen) folgen ihrem
übergeordneten Objekt. Nicht sichtbare Objekte werden wie nicht vorhanden behandelt (404), damit nichts
über fremde Inhalte verraten wird.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.entities import (
    CalculationRun,
    Comparison,
    Datasheet,
    Manufacturer,
    PriceList,
    PriceUpdate,
    Rule,
    User,
)

OWNER = {
    Manufacturer: Manufacturer.owner_id,
    Rule: Rule.owner_id,
    PriceList: PriceList.uploaded_by,
    PriceUpdate: PriceUpdate.created_by,
    Comparison: Comparison.created_by,
    CalculationRun: CalculationRun.created_by,
    Datasheet: Datasheet.owner_id,
}
NOT_FOUND = {
    Manufacturer: "Hersteller nicht gefunden", Rule: "Regel nicht gefunden", PriceList: "Preisliste nicht gefunden",
    PriceUpdate: "Abgleich nicht gefunden", Comparison: "Vergleich nicht gefunden",
    CalculationRun: "Kalkulation nicht gefunden", Datasheet: "Datenblatt nicht gefunden",
}


def is_admin(user: User | None) -> bool:
    return bool(user and user.role == "admin")


def owner_of(obj) -> int | None:
    return getattr(obj, OWNER[type(obj)].key)


def can_see(obj, user: User | None) -> bool:
    return obj is not None and user is not None and (is_admin(user) or owner_of(obj) == user.id)


def visible(stmt, model, user: User):
    """Abfrage auf die Inhalte des Benutzers einschränken (Admin: alles)."""
    return stmt if is_admin(user) else stmt.where(OWNER[model] == user.id)


def get_visible(db: Session, model, obj_id, user: User):
    obj = db.get(model, obj_id) if obj_id is not None else None
    if not can_see(obj, user):
        raise HTTPException(404, NOT_FOUND[model])
    return obj


def visible_or_none(db: Session, model, obj_id, user: User):
    """Wie get_visible, aber None statt 404 (für Formularfelder)."""
    obj = db.get(model, obj_id) if obj_id is not None else None
    return obj if can_see(obj, user) else None
