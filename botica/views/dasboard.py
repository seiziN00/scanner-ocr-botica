"""Panel principal: KPIs con filtro por rango de fechas + vencimientos."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from ..models import Lote, Producto, Venta
from . import render_app

# Filtros de la tabla de vencimientos
FILTROS_VENC = ["todos", "vencidos", "mes", "t3", "t6"]
# Rangos de fecha de los KPIs de ventas
RANGOS = ["hoy", "mes", "custom"]


def _parse_fecha(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor or "")
    except ValueError:
        return None


def _rango_fechas(request) -> tuple[str, date, date]:
    """Resuelve ?rango=hoy|mes|custom (+desde&hasta) a un par de fechas."""
    hoy = timezone.localdate()
    rango = request.GET.get("rango", "hoy")
    if rango not in RANGOS:
        rango = "hoy"
    if rango == "hoy":
        return rango, hoy, hoy
    if rango == "mes":
        return rango, hoy.replace(day=1), hoy
    # custom
    desde = _parse_fecha(request.GET.get("desde")) or hoy
    hasta = _parse_fecha(request.GET.get("hasta")) or hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    return rango, desde, hasta


def _kpis(desde: date, hasta: date) -> dict:
    """Métricas del panel.

    Las de ventas respetan el rango; las de inventario son estado actual
    (una foto del stock no tiene sentido "por rango").
    """
    hoy = timezone.localdate()
    ventas = Venta.objects.filter(
        creada_en__date__gte=desde, creada_en__date__lte=hasta
    ).aggregate(ingresos=Coalesce(Sum("total"), Decimal("0")), tickets=Count("id"))

    productos = Producto.objects.filter(activo=True).annotate(
        stock=Coalesce(Sum("lotes__stock"), 0)
    )
    stock_bajo = productos.filter(stock__gt=0, stock__lte=F("stock_minimo")).count()
    agotados = productos.filter(stock=0).count()
    por_vencer = (
        Lote.objects.filter(
            stock__gt=0,
            fecha_vencimiento__gte=hoy,
            fecha_vencimiento__lte=hoy + timedelta(days=90),
        )
        .values("producto")
        .distinct()
        .count()
    )
    return {
        "ingresos": ventas["ingresos"],
        "tickets": ventas["tickets"],
        "por_vencer": por_vencer,
        "stock_bajo": stock_bajo,
        "agotados": agotados,
    }


def _lotes_vigilancia():
    """Lotes con stock en ventana de vigilancia (vencidos → 180 días)."""
    hoy = timezone.localdate()
    lotes = (
        Lote.objects.filter(stock__gt=0, fecha_vencimiento__lte=hoy + timedelta(days=180))
        .select_related("producto")
        .order_by("fecha_vencimiento", "id")
    )
    for lote in lotes:
        lote.dias = (lote.fecha_vencimiento - hoy).days
    return lotes


def _filtrar_venc(lotes, filtro: str):
    if filtro == "vencidos":
        return [l for l in lotes if l.dias < 0]
    if filtro == "mes":
        return [l for l in lotes if 0 <= l.dias <= 30]
    if filtro == "t3":
        return [l for l in lotes if 30 < l.dias <= 90]
    if filtro == "t6":
        return [l for l in lotes if 90 < l.dias <= 180]
    return list(lotes)


def _conteos_venc(lotes) -> dict:
    return {
        "todos": len(lotes),
        "vencidos": sum(1 for l in lotes if l.dias < 0),
        "mes": sum(1 for l in lotes if 0 <= l.dias <= 30),
        "t3": sum(1 for l in lotes if 30 < l.dias <= 90),
        "t6": sum(1 for l in lotes if 90 < l.dias <= 180),
    }


# --------------------------------------------------------------------- vistas


@login_required
def panel(request):
    rango, desde, hasta = _rango_fechas(request)
    filtro = request.GET.get("f", "todos")
    if filtro not in FILTROS_VENC:
        filtro = "todos"
    lotes = _lotes_vigilancia()
    context = {
        "kpis": _kpis(desde, hasta),
        "rango": rango,
        "desde": desde,
        "hasta": hasta,
        "filtro_venc": filtro,
        "conteos_venc": _conteos_venc(lotes),
        "vencimientos": _filtrar_venc(lotes, filtro),
    }
    return render_app(request, "botica/partials/dashboard.html", context)


@login_required
def panel_kpis(request):
    """HTMX: solo la tira de métricas (target #kpis) + pills OOB."""
    rango, desde, hasta = _rango_fechas(request)
    return render(
        request,
        "botica/partials/panel_kpis_response.html",
        {"kpis": _kpis(desde, hasta), "rango": rango, "desde": desde, "hasta": hasta},
    )


@login_required
def panel_vencimientos(request):
    """HTMX: filas de la tabla + barra de pills vía hx-swap-oob."""
    filtro = request.GET.get("f", "todos")
    if filtro not in FILTROS_VENC:
        filtro = "todos"
    lotes = _lotes_vigilancia()
    return render(
        request,
        "botica/partials/panel_venc_response.html",
        {
            "vencimientos": _filtrar_venc(lotes, filtro),
            "filtro_venc": filtro,
            "conteos_venc": _conteos_venc(lotes),
        },
    )
