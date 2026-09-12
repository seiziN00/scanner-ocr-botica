from django.urls import path

from . import consumers


websocket_urlpatterns = [
    path(
        "ws/sesion/<uuid:session_id>/",
        consumers.SessionConsumer.as_asgi(),
    ),
    # Stream OCR: la app móvil empuja ítems JSON; el desktop recibe <tr> HTML
    path(
        "ws/ocr/<uuid:session_id>/",
        consumers.OcrStreamConsumer.as_asgi(),
    ),
]
