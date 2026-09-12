"""Kardex de producto: cabecera, lotes, historial de movimientos y resumen."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from ..models import Movimiento, Producto, Venta, VentaItem
from . import render_app

MOVS_PAGE_SIZE = 30
PERIODOS = ["7d", "30d", "mes", "custom"]


def _producto(pk: int) -> Producto:
    return get_object_or_404(
        Producto.objects.annotate(stock_total_db=Coalesce(Sum("lotes__stock"), 0)),
        pk=pk,
    )


def _parse_fecha(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor or "")
    except ValueError:
        return None


def _rango_resumen(request) -> tuple[str, date, date]:
    """?periodo=7d|30d|mes|custom (+desde&hasta) → par de fechas."""
    hoy = timezone.localdate()
    periodo = request.GET.get("periodo", "30d")
    if periodo not in PERIODOS:
        periodo = "30d"
    if periodo == "7d":
        return periodo, hoy.fromordinal(hoy.toordinal() - 6), hoy
    if periodo == "30d":
        return periodo, hoy.fromordinal(hoy.toordinal() - 29), hoy
    if periodo == "mes":
        return periodo, hoy.replace(day=1), hoy
    desde = _parse_fecha(request.GET.get("desde")) or hoy.fromordinal(hoy.toordinal() - 29)
    hasta = _parse_fecha(request.GET.get("hasta")) or hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    return periodo, desde, hasta


def _movimientos(request, producto: Producto):
    qs = (
        Movimiento.objects.filter(lote__producto=producto)
        .select_related("lote", "content_type")
        .order_by("-fecha", "-id")
    )
    tipo = request.GET.get("tipo", "")
    if tipo in Movimiento.Tipo.values:
        qs = qs.filter(tipo=tipo)
    desde = _parse_fecha(request.GET.get("desde"))
    hasta = _parse_fecha(request.GET.get("hasta"))
    if desde:
        qs = qs.filter(fecha__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha__date__lte=hasta)
    return qs, tipo, desde, hasta


def _resumen(producto: Producto, desde: date, hasta: date) -> dict:
    """Desglose de cantidades y valores del periodo para el producto."""
    movs = Movimiento.objects.filter(
        lote__producto=producto, fecha__date__gte=desde, fecha__date__lte=hasta
    )
    agg = movs.aggregate(
        entradas=Coalesce(Sum("cantidad", filter=Q(tipo=Movimiento.Tipo.ENTRADA)), 0),
        salidas=Coalesce(Sum("cantidad", filter=Q(tipo=Movimiento.Tipo.SALIDA)), 0),
        mermas=Coalesce(Sum("cantidad", filter=Q(tipo=Movimiento.Tipo.MERMA)), 0),
        autoconsumo=Coalesce(
            Sum("cantidad", filter=Q(tipo=Movimiento.Tipo.AUTOCONSUMO)), 0
        ),
        ajustes=Coalesce(Sum("cantidad", filter=Q(tipo=Movimiento.Tipo.AJUSTE)), 0),
        variacion=Coalesce(Sum("cantidad"), 0),
    )
    # Las salidas se guardan con signo negativo → mostrarlas en positivo
    for clave in ("salidas", "mermas", "autoconsumo"):
        agg[clave] = -agg[clave]
    agg["ventas_soles"] = VentaItem.objects.filter(
        producto=producto,
        venta__creada_en__date__gte=desde,
        venta__creada_en__date__lte=hasta,
    ).aggregate(t=Coalesce(Sum("subtotal"), Decimal("0")))["t"]
    return agg


# --------------------------------------------------------------------- vistas


@login_required
def kardex(request, pk: int):
    producto = _producto(pk)
    lotes = producto.lotes.filter(stock__gt=0).order_by("fecha_vencimiento", "id")
    movs, tipo, mdesde, mhasta = _movimientos(request, producto)
    periodo, desde, hasta = _rango_resumen(request)

    context = {
        "producto": producto,
        "lotes": lotes,
        "stock_lotes": sum(l.stock for l in lotes),
        "valor_inventario": sum(l.valor_inventario for l in lotes),
        "page": Paginator(movs, MOVS_PAGE_SIZE).get_page(request.GET.get("page")),
        "tipos": Movimiento.Tipo.choices,
        "tipo_sel": tipo,
        "mdesde": mdesde,
        "mhasta": mhasta,
        "periodo": periodo,
        "desde": desde,
        "hasta": hasta,
        "resumen": _resumen(producto, desde, hasta),
        "venta_ct": ContentType.objects.get_for_model(Venta).id,
    }
    return render_app(request, "botica/partials/kardex.html", context)


@login_required
@require_GET
def kardex_movimientos(request, pk: int):
    """HTMX: solo las filas del historial (target #kdx-movs)."""
    producto = _producto(pk)
    movs, tipo, desde, hasta = _movimientos(request, producto)
    return render(
        request,
        "botica/partials/kardex_movimientos.html",
        {
            "producto": producto,
            "page": Paginator(movs, MOVS_PAGE_SIZE).get_page(request.GET.get("page")),
            "tipos": Movimiento.Tipo.choices,
            "tipo_sel": tipo,
            "mdesde": desde,
            "mhasta": hasta,
            "venta_ct": ContentType.objects.get_for_model(Venta).id,
        },
    )


@login_required
@require_GET
def kardex_resumen(request, pk: int):
    """HTMX: solo el bloque de resumen del periodo (target #kdx-resumen)."""
    producto = _producto(pk)
    periodo, desde, hasta = _rango_resumen(request)
    return render(
        request,
        "botica/partials/kardex_resumen_response.html",
        {
            "producto": producto,
            "periodo": periodo,
            "desde": desde,
            "hasta": hasta,
            "resumen": _resumen(producto, desde, hasta),
        },
    )


@login_required
@require_GET
def kardex_lotes(request, pk: int):
    """HTMX: filas de lotes + cabecera numérica OOB (tras un movimiento)."""
    producto = _producto(pk)
    lotes = producto.lotes.filter(stock__gt=0).order_by("fecha_vencimiento", "id")
    return render(
        request,
        "botica/partials/kardex_lotes_response.html",
        {
            "producto": producto,
            "lotes": lotes,
            "stock_lotes": sum(l.stock for l in lotes),
            "valor_inventario": sum(l.valor_inventario for l in lotes),
        },
    )
