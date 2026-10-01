"""Feste Antwortschemata der KI. Die KI liefert nur JSON nach diesen Schemata, nie Code.

Jede Antwort wird mit pydantic validiert; ungültige Antworten werden verworfen.
confidence ist bei kleinen Modellen nicht kalibriert und dient nur zur Sortierung.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.excel.columns import FIELDS

FieldName = Literal[tuple(FIELDS)]  # type: ignore[valid-type]


class ColumnAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, le=500)
    field: FieldName | None  # type: ignore[valid-type]


class ColumnSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[ColumnAssignment] = Field(max_length=500)
    manufacturer: str | None = Field(default=None, max_length=200)
    confidence: float = Field(ge=0, le=1)


class MatchJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_article: str = Field(max_length=100)
    old_article: str | None = Field(max_length=100)
    match: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=500)


class RuleSuggestion(BaseModel):
    """Nur ein Vorschlag; wird erst nach Prüfung im Editor gespeichert."""

    model_config = ConfigDict(extra="forbid")
    start_price: Literal["LISTE", "EK", "UVP"]
    steps: list[dict] = Field(min_length=1, max_length=12)
    explanation: str = Field(max_length=1000)
