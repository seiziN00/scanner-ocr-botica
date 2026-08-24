import os
from django.core.asgi import get_asgi_application
from whitenoise.asgi import ASGIStaticFiles  # <--- Importación correcta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from scanner.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    # ASGIStaticFiles adapta la app HTTP para procesar estáticos con la firma ASGI correcta
    "http": ASGIStaticFiles(django_asgi_app),
    "websocket": URLRouter(
        websocket_urlpatterns
    ),
})