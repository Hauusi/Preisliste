from decimal import Decimal

from fastapi.templating import Jinja2Templates

from backend.config import PROJECT_ROOT

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "frontend/templates"))


def money(value) -> str:
    """Decimal deutsch formatieren: 1234.5 -> 1.234,50"""
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    sign = "-" if value < 0 else ""
    text = f"{abs(value):,.2f}" if value == value.quantize(Decimal("0.01")) else f"{abs(value):,}"
    return sign + text.replace(",", "X").replace(".", ",").replace("X", ".")


def dt_de(value) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else ""


def artnr(number, code=None) -> str:
    """Artikelnummer mit Hersteller-Kürzel (Anzeige), z. B. RT + 12345 = RT12345."""
    from backend.services.manufacturers import with_code

    return with_code(number, code) or ""


templates.env.filters["money"] = money
templates.env.filters["artnr"] = artnr
templates.env.filters["dt"] = dt_de
