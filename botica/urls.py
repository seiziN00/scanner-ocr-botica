from django.urls import path

from .views import auth, dasboard, inventario, kardex, pos

app_name = "botica"

urlpatterns = [
    # Autenticación
    path("login/", auth.login_view, name="login"),
    path("logout/", auth.logout_view, name="logout"),

    # Panel principal
    path("", dasboard.panel, name="panel"),
    path("panel/", dasboard.panel, name="panel_alt"),
    path("panel/kpis/", dasboard.panel_kpis, name="panel_kpis"),
    path("panel/vencimientos/", dasboard.panel_vencimientos, name="panel_vencimientos"),

    # Inventario
    path("inventario/", inventario.inventario, name="inventario"),
    path("inventario/filas/", inventario.inventario_filas, name="inventario_filas"),
    path("inventario/kardex/<int:pk>/", kardex.kardex, name="kardex"),
    path("inventario/kardex/<int:pk>/movimientos/", kardex.kardex_movimientos, name="kardex_movimientos"),
    path("inventario/kardex/<int:pk>/resumen/", kardex.kardex_resumen, name="kardex_resumen"),
    path("inventario/kardex/<int:pk>/lotes/", kardex.kardex_lotes, name="kardex_lotes"),
    path("inventario/movimiento/", inventario.movimiento_registrar, name="movimiento"),
    path("inventario/movimiento/form/", inventario.movimiento_form, name="movimiento_form"),
    path("inventario/movimiento/lotes/", inventario.movimiento_lotes, name="movimiento_lotes"),
    path("inventario/metricas/", inventario.inventario_metricas, name="inventario_metricas"),

    # Punto de venta
    path("pos/", pos.pos, name="pos"),
    path("pos/buscar/", pos.pos_buscar, name="pos_buscar"),
    path("pos/checkout/", pos.checkout, name="checkout"),
    path("pos/venta/<int:pk>/", pos.venta_detalle, name="venta_detalle"),
]
