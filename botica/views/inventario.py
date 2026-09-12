"""Inventario: lista agregada de productos + movimientos manuales."""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ..models import Lote, Producto
from ..services import MOTIVOS_ENTRADA, MOTIVOS_SALIDA, registrar_movimiento_manual
from . import render_app

PAGE_SIZE = 25


def _buscar_productos(q: str, estado: str = ""):
    """Productos activos con stock agregado anotado (1 sola query).

    La búsqueda cubre nombre, principio activo, laboratorio y código:
    «paracetamol» devuelve también combinados (ej. Algidol) porque el
    principio activo del combinado lo menciona.

    ``estado``: "bajo" (0 < stock ≤ mínimo) o "agotado" (stock = 0).
    """
    qs = (
        Producto.objects.filter(activo=True)
        .annotate(stock_total_db=Coalesce(Sum("lotes__stock"), 0))
        .order_by("nombre")
    )
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q)
            | Q(principio_activo__icontains=q)
            | Q(laboratorio__icontains=q)
            | Q(codigo__icontains=q)
        )
    if estado == "bajo":
        qs = qs.filter(stock_total_db__gt=0, stock_total_db__lte=F("stock_minimo"))
    elif estado == "agotado":
        qs = qs.filter(stock_total_db=0)
    return qs


def _metricas() -> dict:
    """Cabecera de métricas del inventario (estado actual)."""
    hoy = timezone.localdate()
    productos = Producto.objects.filter(activo=True).annotate(
        stock=Coalesce(Sum("lotes__stock"), 0)
    )
    return {
        "total_productos": productos.count(),
        "total_unidades": productos.aggregate(t=Coalesce(Sum("stock"), 0))["t"],
        "stock_bajo": productos.filter(stock__gt=0, stock__lte=F("stock_minimo")).count(),
        "agotados": productos.filter(stock=0).count(),
        # "Por vencer pronto": ventana de 3 a 6 meses
        "por_vencer": Lote.objects.filter(
            stock__gt=0,
            fecha_vencimiento__gte=hoy + timedelta(days=90),
            fecha_vencimiento__lte=hoy + timedelta(days=180),
        )
        .values("producto")
        .distinct()
        .count(),
    }


def _pagina(request, qs):
    return Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))


# --------------------------------------------------------------------- vistas


@login_required
def inventario(request):
    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    page = _pagina(request, _buscar_productos(q, estado))
    context = {"page": page, "q": q, "estado": estado, "metricas": _metricas()}
    return render_app(request, "botica/partials/inventario.html", context)


@login_required
@require_GET
def inventario_filas(request):
    """HTMX: solo las filas (target #inv-rows)."""
    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    page = _pagina(request, _buscar_productos(q, estado))
    return render(
        request,
        "botica/partials/inv_rows.html",
        {"page": page, "q": q, "estado": estado},
    )


@login_required
@require_GET
def inventario_metricas(request):
    """HTMX: refresco de la tira de métricas (target #inv-metrics)."""
    return render(
        request, "botica/partials/inv_metrics.html", {"metricas": _metricas()}
    )


# ------------------------------------------------------- movimiento manual


def _form_context(**extra) -> dict:
    return {
        "productos": Producto.objects.filter(activo=True).order_by("nombre"),
        "motivos_entrada": MOTIVOS_ENTRADA,
        "motivos_salida": MOTIVOS_SALIDA,
        **extra,
    }


@login_required
@require_GET
def movimiento_form(request):
    """Devuelve el formulario del modal (se carga perezoso al abrirlo)."""
    producto_id = request.GET.get("producto")
    return render(
        request,
        "botica/partials/movimiento_form.html",
        _form_context(producto_sel=producto_id),
    )


@login_required
@require_GET
def movimiento_lotes(request):
    """Opciones del datalist de lotes con stock (?producto=<id>).

    El <select> de producto dispara este hx-get; HTMX incluye
    automáticamente el valor del control que originó el evento.
    """
    lotes = Lote.objects.none()
    producto_id = request.GET.get("producto", "")
    if producto_id.isdigit():
        lotes = Lote.objects.filter(producto_id=producto_id, stock__gt=0).order_by(
            "fecha_vencimiento"
        )
    return render(request, "botica/partials/movimiento_lotes.html", {"lotes": lotes})


@login_required
@require_POST
def movimiento_registrar(request):
    """Registra el movimiento manual del modal (entrada/salida/merma/…)."""
    values = {
        "producto": request.POST.get("producto", ""),
        "direccion": request.POST.get("tipo", ""),
        "motivo_clave": request.POST.get("motivo", ""),
        "cantidad": request.POST.get("cantidad", ""),
        "codigo_lote": request.POST.get("lote", ""),
        "vencimiento": request.POST.get("vencimiento", ""),
        "observacion": request.POST.get("observacion", ""),
    }
    errors: dict[str, str] = {}

    producto = None
    if values["producto"].isdigit():
        producto = Producto.objects.filter(pk=values["producto"], activo=True).first()
    if producto is None:
        errors["producto"] = "Elige un producto válido."

    try:
        cantidad = int(values["cantidad"])
    except (TypeError, ValueError):
        cantidad = 0
        errors["cantidad"] = "Ingresa una cantidad válida."

    fecha_vencimiento = None
    if values["vencimiento"]:
        try:
            # input type="month" → "AAAA-MM"
            fecha_vencimiento = date.fromisoformat(values["vencimiento"] + "-01")
        except ValueError:
            errors["vencimiento"] = "Usa el formato AAAA-MM."

    if not errors:
        try:
            registrar_movimiento_manual(
                producto=producto,
                direccion=values["direccion"],
                motivo_clave=values["motivo_clave"],
                cantidad=cantidad,
                codigo_lote=values["codigo_lote"],
                fecha_vencimiento=fecha_vencimiento,
                observacion=values["observacion"],
                usuario=request.user,
            )
        except ValidationError as exc:
            errors["general"] = "; ".join(exc.messages)

    if errors:
        return render(
            request,
            "botica/partials/movimiento_form.html",
            _form_context(errors=errors, values=values,
                          producto_sel=values["producto"]),
        )

    # 204: HTMX no swappea nada; el evento cierra el modal y refresca
    # las regiones que escuchan "movimientoRegistrado" (from:body).
    response = HttpResponse(status=204)
    response["HX-Trigger"] = json.dumps(
        {"movimientoRegistrado": {"producto": producto.pk}}
    )
    return response
