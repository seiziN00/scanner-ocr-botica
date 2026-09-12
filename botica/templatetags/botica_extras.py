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
def numattr(value) -> str:
    """Número para data-attributes JS: siempre con punto decimal.

    Las plantillas localizan Decimales según LANGUAGE_CODE (es-PE → coma),
    lo que rompería ``parseFloat``/``Number`` en app.js.
    """
    try:
        return f"{Decimal(str(value)):.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "0"


@register.filter
def fecha(value) -> str:
    """date/datetime → dd/mm/aaaa."""
    if not value:
        return "—"
    if isinstance(value, (date,)):
        return value.strftime("%d/%m/%Y")
    return str(value)


@register.filter
def cantidad_signo(value) -> str:
    """+200 / −6 para la columna Cantidad del kardex."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "0"
    if n > 0:
        return f"+{n}"
    if n < 0:
        return f"−{abs(n)}"  # signo menos tipográfico
    return "0"


@register.filter
def dias_texto(dias) -> str:
    """Texto humano para el toggle de vencimiento del panel."""
    try:
        d = int(dias)
    except (TypeError, ValueError):
        return ""
    if d < 0:
        return f"Venció hace {abs(d)} día{'s' if abs(d) != 1 else ''}"
    if d == 0:
        return "Vence hoy"
    return f"Faltan {d} día{'s' if d != 1 else ''}"
