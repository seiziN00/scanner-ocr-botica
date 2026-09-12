"""Modelo de dominio de la botica.

Tres pilares conceptuales:

1. ``Producto``    — el "qué tengo" agregado (catálogo, precios, equivalencias).
2. ``Lote``        — la existencia física específica (código de lote, vencimiento).
3. ``Movimiento``  — el kardex: la pista de auditoría del "por qué lo tengo".

Las transacciones (``Venta`` / ``Compra``) disparan movimientos de kardex
automáticos a través de ``botica.services`` (nunca se descuenta stock a mano
en las vistas: la lógica FIFO y los bloqueos de concurrencia viven allí).
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from django.utils import timezone


# ---------------------------------------------------------------------------
# Usuario personalizado (autenticación solo con email)
# ---------------------------------------------------------------------------


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("El email es obligatorio.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra.get("is_staff") is not True:
            raise ValueError("El superusuario debe tener is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("El superusuario debe tener is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Usuario del sistema: sin username, el email es la credencial única."""

    email = models.EmailField("correo electrónico", unique=True)
    nombre = models.CharField("nombre", max_length=120, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self) -> str:
        return self.email

    @property
    def nombre_corto(self) -> str:
        return self.nombre.split()[0] if self.nombre else self.email.split("@")[0]


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------


class TipoUnidad(models.TextChoices):
    """Presentaciones de venta. El inventario SIEMPRE se guarda en UNIDAD."""

    UNIDAD = "UNIDAD", "Unidad"
    BLISTER = "BLISTER", "Blíster"
    CAJA = "CAJA", "Caja"


class Producto(models.Model):
    """El "qué tengo": datos agregados del producto (nunca stock por fila).

    El stock real vive en los lotes; aquí solo se define el catálogo, los
    precios por presentación y los factores de equivalencia:

        1 caja    = blisters_por_caja blísters
        1 blíster = unidades_por_blister unidades

    Un factor en 0 significa "no se vende en esa presentación".
    """

    codigo = models.CharField(max_length=20, unique=True)  # índice implícito (unique)
    nombre = models.CharField(max_length=200)
    principio_activo = models.CharField(max_length=200, blank=True, db_index=True)
    concentracion = models.CharField(max_length=80, blank=True)
    presentacion = models.CharField(max_length=80, blank=True)
    laboratorio = models.CharField(max_length=120, blank=True)
    stock_minimo = models.PositiveIntegerField(default=0)
    # Precio de venta por UNIDAD (precio base)
    precio_venta = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    precio_blister = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    precio_caja = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0"))
    # Factores de equivalencia (0 = esa presentación no aplica)
    unidades_por_blister = models.PositiveIntegerField(default=0)
    blisters_por_caja = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["nombre"]
        indexes = [
            models.Index(fields=["nombre"], name="producto_nombre_idx"),
        ]

    def __str__(self) -> str:
        partes = [self.nombre]
        if self.concentracion:
            partes.append(self.concentracion)
        if self.presentacion:
            partes.append(f"· {self.presentacion}")
        return " ".join(partes)

    def get_absolute_url(self) -> str:
        return reverse("botica:kardex", args=[self.pk])

    # ----- stock agregado -------------------------------------------------
    @property
    def stock_total(self) -> int:
        """Suma del stock de los lotes.

        Las vistas anotan ``stock_total_db`` (Sum de lotes) para evitar N+1;
        si la anotación existe se usa, si no se calcula (1 query extra).
        """
        annotated = getattr(self, "stock_total_db", None)
        if annotated is not None:
            return int(annotated)
        return sum(self.lotes.values_list("stock", flat=True) or [0])

    # ----- equivalencias --------------------------------------------------
    @property
    def unidades_por_caja(self) -> int:
        return self.unidades_por_blister * self.blisters_por_caja

    def factor_unidad(self, tipo: str) -> int:
        """Cuántas unidades base contiene una presentación (0 = no aplica)."""
        if tipo == TipoUnidad.UNIDAD:
            return 1
        if tipo == TipoUnidad.BLISTER:
            return self.unidades_por_blister
        if tipo == TipoUnidad.CAJA:
            return self.unidades_por_caja
        return 0

    def precio_para(self, tipo: str) -> Decimal:
        """Precio de venta de UNA presentación (unidad / blíster / caja)."""
        if tipo == TipoUnidad.BLISTER and self.precio_blister is not None:
            return self.precio_blister
        if tipo == TipoUnidad.CAJA and self.precio_caja is not None:
            return self.precio_caja
        return self.precio_venta

    def stock_para(self, tipo: str, stock_base: int | None = None) -> int:
        """Stock disponible expresado en la presentación pedida."""
        if stock_base is None:
            stock_base = self.stock_total
        factor = self.factor_unidad(tipo)
        if factor <= 0:
            return 0
        return stock_base // factor

    # ----- estado comercial -------------------------------------------------
    def estado_stock(self, stock_base: int | None = None) -> str:
        """'agotado' | 'bajo' | 'ok' — para badges y métricas."""
        if stock_base is None:
            stock_base = self.stock_total
        if stock_base <= 0:
            return "agotado"
        if stock_base <= self.stock_minimo:
            return "bajo"
        return "ok"


class Lote(models.Model):
    """La existencia física: un lote concreto con su vencimiento y su stock."""

    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name="lotes"
    )
    codigo_lote = models.CharField(max_length=60, db_index=True)
    fecha_vencimiento = models.DateField(db_index=True)
    stock = models.PositiveIntegerField(default=0)  # en unidades base
    # costo de ESTE lote (para valorizar el inventario con costo real FIFO)
    costo_unitario = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["fecha_vencimiento", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "codigo_lote"], name="lote_unico_por_producto"
            )
        ]
        indexes = [
            models.Index(fields=["producto", "fecha_vencimiento"], name="lote_prod_venc_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.codigo_lote} · {self.producto.nombre}"

    @property
    def costo(self) -> Decimal:
        """Costo unitario efectivo del lote (cae al costo del producto)."""
        if self.costo_unitario is not None:
            return self.costo_unitario
        return self.producto.costo_unitario

    @property
    def valor_inventario(self) -> Decimal:
        return self.costo * self.stock


# ---------------------------------------------------------------------------
# Kardex
# ---------------------------------------------------------------------------


class Movimiento(models.Model):
    """La pista de auditoría: por qué cambió el stock de un lote.

    ``cantidad`` es CON SIGNO (positivo = entra stock, negativo = sale) para
    que los resúmenes de periodo sean un simple ``Sum``.

    ``saldo_resultante`` es el stock total del PRODUCTO inmediatamente
    después del movimiento (saldo corrido del kardex).

    ``referencia`` es una llave genérica al documento origen (Venta/Compra).
    """

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SALIDA = "SALIDA", "Salida"
        MERMA = "MERMA", "Merma"
        AUTOCONSUMO = "AUTOCONSUMO", "Autoconsumo"
        AJUSTE = "AJUSTE", "Ajuste"

    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    tipo = models.CharField(max_length=12, choices=Tipo.choices, db_index=True)
    motivo = models.CharField(max_length=200)
    lote = models.ForeignKey(
        Lote, on_delete=models.PROTECT, related_name="movimientos"
    )
    cantidad = models.IntegerField()  # con signo
    saldo_resultante = models.IntegerField()  # stock del producto tras el movimiento
    # Referencia genérica al documento origen (Venta, Compra…)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    referencia = GenericForeignKey("content_type", "object_id")
    usuario = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="movimientos",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        indexes = [
            models.Index(fields=["lote", "fecha"], name="mov_lote_fecha_idx"),
            models.Index(fields=["tipo", "fecha"], name="mov_tipo_fecha_idx"),
            models.Index(fields=["content_type", "object_id"], name="mov_gfk_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.cantidad:+d} · {self.lote.codigo_lote}"

    @property
    def es_entrada(self) -> bool:
        return self.cantidad > 0


# ---------------------------------------------------------------------------
# Transacciones (disparan movimientos automáticos vía services)
# ---------------------------------------------------------------------------


class Secuencia(models.Model):
    """Contador atómico para numeración de comprobantes (tickets, etc.).

    Se incrementa con ``select_for_update`` dentro de la transacción de la
    venta: jamás hay tickets duplicados ni huecos por carrera.
    """

    nombre = models.CharField(max_length=40, primary_key=True)
    valor = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.nombre}={self.valor}"


class Venta(models.Model):
    """Ticket de venta. Al confirmarse descuenta stock FIFO por vencimiento."""

    class MetodoPago(models.TextChoices):
        EFECTIVO = "efectivo", "Efectivo"
        YAPE = "yape", "Yape"
        PLIN = "plin", "Plin"
        TRANSFERENCIA = "transf", "Transferencia"

    numero = models.PositiveIntegerField(unique=True, editable=False)
    creada_en = models.DateTimeField(default=timezone.now, db_index=True)
    metodo_pago = models.CharField(
        max_length=10, choices=MetodoPago.choices, default=MetodoPago.EFECTIVO
    )
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    vendedor = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas"
    )

    class Meta:
        ordering = ["-creada_en", "-id"]

    def __str__(self) -> str:
        return f"Ticket {self.ticket}"

    @property
    def ticket(self) -> str:
        """Número formateado para mostrar: 000438."""
        return f"{self.numero:06d}"

    @property
    def cantidad_items(self) -> int:
        return sum(i.cantidad for i in self.items.all())


class VentaItem(models.Model):
    """Línea del ticket. ``cantidad_base`` es lo que se descontó del stock."""

    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="ventas"
    )
    tipo_unidad = models.CharField(max_length=10, choices=TipoUnidad.choices)
    cantidad = models.PositiveIntegerField()  # presentaciones vendidas
    cantidad_base = models.PositiveIntegerField()  # unidades base descontadas
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.producto.nombre} x{self.cantidad} {self.get_tipo_unidad_display()}"


class Compra(models.Model):
    """Ingreso de mercadería (factura de proveedor). Crea lotes + entradas."""

    proveedor = models.CharField(max_length=160, blank=True)
    comprobante = models.CharField(max_length=40, blank=True)  # ej. F001-00482
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    registrada_por = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self) -> str:
        return f"Compra {self.comprobante or self.pk} · {self.proveedor or '—'}"


class CompraItem(models.Model):
    """Detalle de la compra; cada ítem genera/actualiza un lote."""

    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="compras"
    )
    codigo_lote = models.CharField(max_length=60)
    fecha_vencimiento = models.DateField()
    cantidad = models.PositiveIntegerField()  # unidades base
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0"))

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.producto.nombre} x{self.cantidad} ({self.codigo_lote})"

    @property
    def subtotal(self) -> Decimal:
        return self.costo_unitario * self.cantidad
