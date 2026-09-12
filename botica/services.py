"""
Lógica de negocio del inventario.
Reglas duras:

* TODO cambio de stock pasa por aquí (las vistas nunca tocan Lote.stock).
* Toda deducción se hace dentro de transaction.atomic() bloqueando primero
  la fila del Producto y después sus Lotes con select_for_update()
  (siempre en ese orden → sin deadlocks ni race conditions).
* Las salidas comerciales usan FEFO.
* Cada cambio deja su Movimiento de kardex con saldo_resultante
  (saldo corrido del producto) y, si aplica, la referencia al documento
  origen (Venta / Compra).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum

from .models import (
    Compra,
    CompraItem,
    Lote,
    Movimiento,
    Producto,
    Secuencia,
    TipoUnidad,
    Venta,
    VentaItem,
)

LOTE_INICIAL = "SIN-LOTE"
FECHA_CENTINELA = date(2099, 12, 31)


class StockInsuficiente(ValidationError):
    """El stock disponible no alcanza para la operación pedida."""

    def __init__(self, producto: Producto, pedido: int, disponible: int):
        self.producto = producto
        self.pedido = pedido
        self.disponible = disponible
        super().__init__(
            f"Stock insuficiente de «{producto.nombre}»: "
            f"se pidieron {pedido} uds. y hay {disponible}."
        )


# ---------------------------------------------------------------------------
# Primitivas de kardex
# ---------------------------------------------------------------------------


def _saldo_producto(producto: Producto) -> int:
    """Stock total del producto. Llamar SIEMPRE con el producto bloqueado."""
    return (
        producto.lotes.aggregate(t=Sum("stock"))["t"] or 0
    )


def _crear_movimiento(
    *,
    lote: Lote,
    tipo: str,
    cantidad: int,
    saldo: int,
    motivo: str,
    referencia=None,
    usuario=None,
) -> Movimiento:
    return Movimiento.objects.create(
        lote=lote,
        tipo=tipo,
        cantidad=cantidad,
        saldo_resultante=saldo,
        motivo=motivo,
        referencia=referencia,
        usuario=usuario,
    )


@transaction.atomic
def registrar_entrada(
    *,
    producto: Producto,
    codigo_lote: str,
    fecha_vencimiento: date,
    cantidad: int,
    motivo: str,
    costo_unitario: Decimal | None = None,
    referencia=None,
    usuario=None,
    tipo: str = Movimiento.Tipo.ENTRADA,
) -> Movimiento:
    """Suma stock a un lote (lo crea si no existe) y deja el movimiento."""
    if cantidad <= 0:
        raise ValidationError("La cantidad de entrada debe ser positiva.")
    codigo_lote = (codigo_lote or "").strip()
    if not codigo_lote:
        raise ValidationError("El código de lote es obligatorio.")

    # Bloqueo en orden fijo: producto → lote
    producto = Producto.objects.select_for_update().get(pk=producto.pk)
    lote, creado = Lote.objects.select_for_update().get_or_create(
        producto=producto,
        codigo_lote=codigo_lote,
        defaults={
            "fecha_vencimiento": fecha_vencimiento,
            "stock": 0,
            "costo_unitario": costo_unitario,
        },
    )
    if not creado and costo_unitario is not None:
        lote.costo_unitario = costo_unitario

    # Incremento atómico a nivel de fila
    lote.stock = F("stock") + cantidad
    lote.save(update_fields=["stock", "costo_unitario"])
    lote.refresh_from_db(fields=["stock"])

    saldo = _saldo_producto(producto)
    return _crear_movimiento(
        lote=lote, tipo=tipo, cantidad=cantidad, saldo=saldo,
        motivo=motivo, referencia=referencia, usuario=usuario,
    )


@transaction.atomic
def descontar_fifo(
    *,
    producto: Producto,
    cantidad_base: int,
    motivo: str,
    referencia=None,
    usuario=None,
    tipo: str = Movimiento.Tipo.SALIDA,
) -> list[Movimiento]:
    """Descuenta ``cantidad_base`` unidades con estrategia FEFO/FIFO.

    Toma primero del lote con vencimiento más próximo. Devuelve los
    movimientos generados (uno por lote afectado).
    """
    if cantidad_base <= 0:
        raise ValidationError("La cantidad a descontar debe ser positiva.")

    producto = Producto.objects.select_for_update().get(pk=producto.pk)
    lotes = list(
        producto.lotes.select_for_update()
        .filter(stock__gt=0)
        .order_by("fecha_vencimiento", "id")
    )
    disponible = sum(l.stock for l in lotes)
    if disponible < cantidad_base:
        raise StockInsuficiente(producto, cantidad_base, disponible)

    movimientos: list[Movimiento] = []
    restante = cantidad_base
    saldo = disponible  # saldo corrido a nivel producto
    for lote in lotes:
        if restante <= 0:
            break
        tomar = min(lote.stock, restante)
        lote.stock = F("stock") - tomar
        lote.save(update_fields=["stock"])
        lote.refresh_from_db(fields=["stock"])
        restante -= tomar
        saldo -= tomar
        movimientos.append(
            _crear_movimiento(
                lote=lote, tipo=tipo, cantidad=-tomar, saldo=saldo,
                motivo=motivo, referencia=referencia, usuario=usuario,
            )
        )
    return movimientos


@transaction.atomic
def descontar_de_lote(
    *,
    lote_id: int,
    cantidad_base: int,
    motivo: str,
    usuario=None,
    tipo: str = Movimiento.Tipo.MERMA,
) -> Movimiento:
    """Descuento dirigido a UN lote concreto (mermas, ajustes manuales)."""
    if cantidad_base <= 0:
        raise ValidationError("La cantidad a descontar debe ser positiva.")

    lote = Lote.objects.select_for_update().select_related("producto").get(pk=lote_id)
    # Bloquear también el producto para un saldo_resultante consistente
    producto = Producto.objects.select_for_update().get(pk=lote.producto_id)
    if lote.stock < cantidad_base:
        raise StockInsuficiente(producto, cantidad_base, lote.stock)

    lote.stock = F("stock") - cantidad_base
    lote.save(update_fields=["stock"])
    lote.refresh_from_db(fields=["stock"])

    saldo = _saldo_producto(producto)
    return _crear_movimiento(
        lote=lote, tipo=tipo, cantidad=-cantidad_base, saldo=saldo,
        motivo=motivo, usuario=usuario,
    )


# ---------------------------------------------------------------------------
# Ventas (POS)
# ---------------------------------------------------------------------------


def _proximo_numero_venta() -> int:
    """Ticket siguiente, atómico (fila de Secuencia bloqueada)."""
    sec, _ = Secuencia.objects.select_for_update().get_or_create(nombre="venta")
    sec.valor += 1
    sec.save(update_fields=["valor"])
    return sec.valor


def proximo_ticket() -> str:
    """Número que se MOSTRARÁ en el POS (solo informativo)."""
    sec = Secuencia.objects.filter(nombre="venta").first()
    return f"{(sec.valor if sec else 0) + 1:06d}"


@transaction.atomic
def confirmar_venta(
    *,
    items: list[dict],
    metodo_pago: str,
    usuario,
    descuento: Decimal = Decimal("0"),
) -> Venta:
    """Confirma el carrito del POS.

    ``items``: lista de ``{"codigo", "tipo_unidad", "cantidad"}`` donde
    ``cantidad`` se expresa en la presentación elegida (unidad/blíster/caja).

    Crea la ``Venta`` con sus ítems y descuenta el stock con FIFO,
    generando los movimientos ``SALIDA`` referenciados a la venta.
    """
    if not items:
        raise ValidationError("El carrito está vacío.")
    if metodo_pago not in Venta.MetodoPago.values:
        raise ValidationError("Método de pago no válido.")
    if descuento < 0:
        raise ValidationError("El descuento no puede ser negativo.")

    venta = Venta(
        numero=_proximo_numero_venta(),
        metodo_pago=metodo_pago,
        vendedor=usuario if getattr(usuario, "is_authenticated", False) else None,
        descuento=descuento,
    )

    bruto = Decimal("0")
    lineas: list[tuple[Producto, str, int, int, Decimal]] = []
    for it in items:
        producto = Producto.objects.get(codigo=it["codigo"], activo=True)
        tipo_unidad = it["tipo_unidad"]
        cantidad = int(it["cantidad"])
        factor = producto.factor_unidad(tipo_unidad)
        if factor <= 0:
            raise ValidationError(
                f"«{producto.nombre}» no se vende por "
                f"{TipoUnidad(tipo_unidad).label.lower()}."
            )
        if cantidad <= 0:
            raise ValidationError("Las cantidades deben ser positivas.")
        precio = producto.precio_para(tipo_unidad)
        cantidad_base = cantidad * factor
        bruto += precio * cantidad
        lineas.append((producto, tipo_unidad, cantidad, cantidad_base, precio))

    if descuento > bruto:
        raise ValidationError("El descuento no puede superar el total.")

    venta.total = bruto - descuento
    venta.save()

    for producto, tipo_unidad, cantidad, cantidad_base, precio in lineas:
        VentaItem.objects.create(
            venta=venta,
            producto=producto,
            tipo_unidad=tipo_unidad,
            cantidad=cantidad,
            cantidad_base=cantidad_base,
            precio_unitario=precio,
            subtotal=precio * cantidad,
        )
        descontar_fifo(
            producto=producto,
            cantidad_base=cantidad_base,
            motivo=f"Venta Comercial · Ticket {venta.ticket}",
            referencia=venta,
            usuario=venta.vendedor,
            tipo=Movimiento.Tipo.SALIDA,
        )
    return venta


# ---------------------------------------------------------------------------
# Compras (ingreso de mercadería)
# ---------------------------------------------------------------------------


@transaction.atomic
def registrar_compra(
    *,
    items: list[dict],
    usuario,
    proveedor: str = "",
    comprobante: str = "",
) -> Compra:
    """Registra una compra: crea/actualiza lotes y movimientos ENTRADA.

    ``items``: ``{"producto_id", "codigo_lote", "fecha_vencimiento",
    "cantidad", "costo_unitario"}`` (cantidad en unidades base).
    """
    if not items:
        raise ValidationError("La compra no tiene ítems.")

    compra = Compra.objects.create(
        proveedor=proveedor.strip(),
        comprobante=comprobante.strip(),
        registrada_por=usuario if getattr(usuario, "is_authenticated", False) else None,
    )
    total = Decimal("0")
    for it in items:
        producto = Producto.objects.get(pk=it["producto_id"])
        cantidad = int(it["cantidad"])
        costo = Decimal(str(it.get("costo_unitario", 0)))
        CompraItem.objects.create(
            compra=compra,
            producto=producto,
            codigo_lote=it["codigo_lote"].strip(),
            fecha_vencimiento=it["fecha_vencimiento"],
            cantidad=cantidad,
            costo_unitario=costo,
        )
        total += costo * cantidad
        registrar_entrada(
            producto=producto,
            codigo_lote=it["codigo_lote"],
            fecha_vencimiento=it["fecha_vencimiento"],
            cantidad=cantidad,
            costo_unitario=costo,
            motivo=f"Compra · Fact. {compra.comprobante or compra.pk}",
            referencia=compra,
            usuario=usuario,
        )
    compra.total = total
    compra.save(update_fields=["total"])
    return compra


# ---------------------------------------------------------------------------
# Movimiento manual (modal "Registrar movimiento")
# ---------------------------------------------------------------------------

# motivo del formulario → tipo de movimiento de kardex
MOTIVOS_SALIDA = {
    "venta": (Movimiento.Tipo.SALIDA, "Venta Comercial (manual)"),
    "vencido": (Movimiento.Tipo.MERMA, "Medicamento Vencido / Caducado"),
    "deterioro": (Movimiento.Tipo.MERMA, "Deterioro / Rotura / Derrame"),
    "uso_interno": (Movimiento.Tipo.AUTOCONSUMO, "Retiro para uso interno / Botiquín"),
    "donacion": (Movimiento.Tipo.SALIDA, "Donación / Muestras Médicas"),
}
MOTIVOS_ENTRADA = {
    "compra": (Movimiento.Tipo.ENTRADA, "Compra / Ingreso de mercadería"),
    "ajuste": (Movimiento.Tipo.AJUSTE, "Ajuste por conteo físico"),
}


@transaction.atomic
def registrar_movimiento_manual(
    *,
    producto: Producto,
    direccion: str,  # "entrada" | "salida"
    motivo_clave: str,
    cantidad: int,
    usuario,
    codigo_lote: str = "",
    fecha_vencimiento: date | None = None,
    observacion: str = "",
) -> Movimiento | list[Movimiento]:
    """Movimiento registrado a mano desde el modal de inventario/kardex."""
    if cantidad <= 0:
        raise ValidationError("La cantidad debe ser al menos 1.")

    obs = observacion.strip()
    if direccion == "entrada":
        tipo, motivo = MOTIVOS_ENTRADA.get(
            motivo_clave, (Movimiento.Tipo.ENTRADA, "Ingreso manual")
        )
        if not codigo_lote.strip():
            raise ValidationError("Para una entrada debes indicar el lote.")
        if fecha_vencimiento is None:
            raise ValidationError("Para una entrada debes indicar el vencimiento.")
        return registrar_entrada(
            producto=producto,
            codigo_lote=codigo_lote,
            fecha_vencimiento=fecha_vencimiento,
            cantidad=cantidad,
            motivo=f"{motivo}{' · ' + obs if obs else ''}",
            usuario=usuario,
            tipo=tipo,
        )

    if direccion == "salida":
        tipo, motivo = MOTIVOS_SALIDA.get(
            motivo_clave, (Movimiento.Tipo.SALIDA, "Salida manual")
        )
        motivo = f"{motivo}{' · ' + obs if obs else ''}"
        # Si se indicó un lote existente, el descuento es dirigido;
        # si no, se aplica el FIFO habitual.
        if codigo_lote.strip():
            lote = Lote.objects.filter(
                producto=producto, codigo_lote__iexact=codigo_lote.strip()
            ).first()
            if lote is not None:
                return descontar_de_lote(
                    lote_id=lote.pk, cantidad_base=cantidad,
                    motivo=motivo, usuario=usuario, tipo=tipo,
                )
        return descontar_fifo(
            producto=producto, cantidad_base=cantidad,
            motivo=motivo, usuario=usuario, tipo=tipo,
        )

    raise ValidationError("Dirección de movimiento no válida.")
