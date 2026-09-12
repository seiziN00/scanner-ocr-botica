from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Compra,
    CompraItem,
    Lote,
    Movimiento,
    Producto,
    Secuencia,
    User,
    Venta,
    VentaItem,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Usuario con email como credencial (sin username)."""

    ordering = ["email"]
    list_display = ["email", "nombre", "is_staff", "is_active", "date_joined"]
    search_fields = ["email", "nombre"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos", {"fields": ("nombre",)}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "nombre", "password1", "password2"),
        }),
    )


class LoteInline(admin.TabularInline):
    model = Lote
    extra = 0
    fields = ["codigo_lote", "fecha_vencimiento", "stock", "costo_unitario"]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "laboratorio", "precio_venta", "stock_minimo", "activo"]
    list_filter = ["activo", "laboratorio"]
    search_fields = ["codigo", "nombre", "principio_activo"]
    inlines = [LoteInline]


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = ["codigo_lote", "producto", "fecha_vencimiento", "stock"]
    list_filter = ["fecha_vencimiento"]
    search_fields = ["codigo_lote", "producto__nombre"]
    autocomplete_fields = ["producto"]


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tipo", "lote", "cantidad", "saldo_resultante", "usuario"]
    list_filter = ["tipo", "fecha"]
    search_fields = ["lote__codigo_lote", "lote__producto__nombre", "motivo"]
    readonly_fields = ["created_at"]
    # Los movimientos nacen de las operaciones, no se editan a mano
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class VentaItemInline(admin.TabularInline):
    model = VentaItem
    extra = 0
    readonly_fields = ["producto", "tipo_unidad", "cantidad", "cantidad_base", "precio_unitario", "subtotal"]
    can_delete = False


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ["ticket", "creada_en", "metodo_pago", "total", "vendedor"]
    list_filter = ["metodo_pago", "creada_en"]
    search_fields = ["numero"]
    inlines = [VentaItemInline]
    readonly_fields = ["numero", "creada_en", "total"]


class CompraItemInline(admin.TabularInline):
    model = CompraItem
    extra = 0


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    list_display = ["comprobante", "proveedor", "fecha", "total"]
    search_fields = ["comprobante", "proveedor"]
    inlines = [CompraItemInline]


@admin.register(Secuencia)
class SecuenciaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "valor"]
