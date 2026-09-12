"""Punto de venta: búsqueda en tiempo real, checkout FIFO y detalle de venta."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from ..models import Producto, TipoUnidad, Venta
from ..services import confirmar_venta, proximo_ticket
from . import render_app

MAX_RESULTADOS = 50


def _buscar(q: str):
    """Productos vendibles con stock anotado. Búsqueda por nombre,
    principio activo o código (un solo query, sin N+1)."""
    qs = (
        Producto.objects.filter(activo=True)
        .annotate(stock_total_db=Coalesce(Sum("lotes__stock"), 0))
        .order_by("nombre")
    )
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q)
            | Q(principio_activo__icontains=q)
            | Q(codigo__icontains=q)
        )
    return qs[:MAX_RESULTADOS]


def _fila(p: Producto) -> dict:
    """Lo que la fila/tarjeta del POS necesita (data-attributes del diseño)."""
    stock = p.stock_total
    return {
        "pk": p.pk,
        "codigo": p.codigo,
        "nombre": str(p),
        "principio_activo": p.principio_activo,
        "key": f"{p.nombre} {p.principio_activo} {p.codigo}".lower(),
        "stock": stock,
        "agotado": stock <= 0,
        "bajo": 0 < stock <= p.stock_minimo,
        # precios por presentación (0 = no se vende así)
        "p_uni": p.precio_venta,
        "p_blis": p.precio_blister or Decimal("0"),
        "p_caja": p.precio_caja or Decimal("0"),
        # stock por presentación (0 = opción deshabilitada en el popover)
        "s_uni": stock,
        "s_blis": p.stock_para(TipoUnidad.BLISTER, stock),
        "s_caja": p.stock_para(TipoUnidad.CAJA, stock),
    }


# --------------------------------------------------------------------- vistas


@login_required
def pos(request):
    context = {
        "productos": [_fila(p) for p in _buscar("")],
        "ticket": proximo_ticket(),
    }
    return render_app(request, "botica/partials/pos.html", context)


@login_required
@require_GET
def pos_buscar(request):
    """HTMX: resultados del buscador (target #pos-results)."""
    q = request.GET.get("q", "").strip()
    return render(
        request,
        "botica/partials/pos_results.html",
        {"productos": [_fila(p) for p in _buscar(q)], "q": q},
    )


@login_required
@require_POST
def checkout(request):
    """Confirma la venta del carrito (JSON) con descuento FIFO de stock."""
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Cuerpo JSON inválido."}, status=400)

    # Sanitizar el carrito
    items: list[dict] = []
    for raw in payload.get("items", [])[:200]:
        try:
            codigo = str(raw["codigo"])[:20]
            tipo_unidad = str(raw["tipo_unidad"]).upper()
            cantidad = int(raw["cantidad"])
        except (KeyError, TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "error": "Ítem de carrito mal formado."}, status=400
            )
        if tipo_unidad not in TipoUnidad.values:
            return JsonResponse(
                {"ok": False, "error": f"Presentación no válida: {tipo_unidad}."},
                status=400,
            )
        if cantidad <= 0 or cantidad > 100_000:
            return JsonResponse(
                {"ok": False, "error": "Cantidad fuera de rango."}, status=400
            )
        items.append(
            {"codigo": codigo, "tipo_unidad": tipo_unidad, "cantidad": cantidad}
        )

    try:
        descuento = Decimal(str(payload.get("descuento", 0) or 0))
    except (InvalidOperation, ValueError):
        return JsonResponse({"ok": False, "error": "Descuento inválido."}, status=400)

    try:
        venta = confirmar_venta(
            items=items,
            metodo_pago=str(payload.get("metodo", "efectivo")),
            usuario=request.user,
            descuento=descuento,
        )
    except Producto.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": "Un producto del carrito ya no existe."}, status=400
        )
    except ValidationError as exc:
        return JsonResponse(
            {"ok": False, "error": "; ".join(exc.messages)}, status=400
        )

    return JsonResponse(
        {
            "ok": True,
            "ticket": venta.ticket,
            "total": f"{venta.total:.2f}",
            "metodo": venta.get_metodo_pago_display(),
            "proximo_ticket": proximo_ticket(),
        }
    )


@login_required
@require_GET
def venta_detalle(request, pk: int):
    """Detalle del ticket (modal). Lo enlazan las SALIDA del kardex."""
    venta = get_object_or_404(
        Venta.objects.prefetch_related("items__producto").select_related("vendedor"),
        pk=pk,
    )
    return render(request, "botica/partials/venta_detalle.html", {"venta": venta})
