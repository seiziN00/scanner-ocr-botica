from datetime import date
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def soles(value) -> str:
    """Formatea un monto como S/ 1,234.56."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        amount = Decimal("0")
    return f"S/ {amount:,.2f}"


@register.filter
def fmt_venc(value) -> str:
    """YYYY-MM -> MM/YYYY. Cadena vacía -> —."""
    value = (value or "").strip()
    if len(value) == 7 and value[4] == "-":
        return f"{value[5:7]}/{value[0:4]}"
    return value or "—"


@register.filter
def vence_pronto(value) -> bool:
    """True si el vencimiento (YYYY-MM) ya pasó o es el mes actual."""
    value = (value or "").strip()
    if len(value) != 7:
        return False
    today = date.today()
    return value <= f"{today.year:04d}-{today.month:02d}"
