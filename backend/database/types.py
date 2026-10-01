"""Decimal als TEXT speichern. SQLite hat keinen exakten Dezimaltyp, REAL wäre float."""

from decimal import Decimal

from sqlalchemy.types import String, TypeDecorator


class DecimalText(TypeDecorator):
    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("float ist für Geldbeträge nicht erlaubt, Decimal verwenden")
        if not isinstance(value, Decimal):
            value = Decimal(value)
        if not value.is_finite():
            raise ValueError("Nur endliche Dezimalwerte erlaubt")
        return format(value, "f")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)
