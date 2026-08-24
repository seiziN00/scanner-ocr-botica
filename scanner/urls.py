from django.urls import path

from . import views

app_name = "scanner"

urlpatterns = [
    path("", views.index, name="index"),
    path("procesar/", views.process, name="process"),
    path("s/<uuid:session_id>/", views.session_workspace, name="workspace"),
    path("s/<uuid:session_id>/estado/", views.session_state, name="state"),
    path(
        "s/<uuid:session_id>/items/nuevo/",
        views.item_create_form,
        name="item_create_form",
    ),
    path(
        "s/<uuid:session_id>/items/nuevo/guardar/",
        views.item_create,
        name="item_create",
    ),
    path(
        "s/<uuid:session_id>/items/<uuid:item_id>/editar/",
        views.item_update_form,
        name="item_update_form",
    ),
    path(
        "s/<uuid:session_id>/items/<uuid:item_id>/editar/guardar/",
        views.item_update,
        name="item_update",
    ),
    path(
        "s/<uuid:session_id>/items/<uuid:item_id>/eliminar/",
        views.item_delete_form,
        name="item_delete_form",
    ),
    path(
        "s/<uuid:session_id>/items/<uuid:item_id>/eliminar/confirmar/",
        views.item_delete,
        name="item_delete",
    ),
    path("s/<uuid:session_id>/continuar-pc/", views.pair_help, name="pair_help"),
    path("s/<uuid:session_id>/exportar/", views.session_export, name="export"),
    path("s/<uuid:session_id>/cerrar/", views.session_close, name="close"),
    path("continuar/", views.pair_desktop, name="pair_desktop"),
    path(
        "continuar/estado/<str:token>/", views.pair_status, name="pair_status"
    ),
    path("vincular/<str:token>/", views.pair_mobile, name="pair_mobile"),
]
