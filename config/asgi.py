import os
from django.core.asgi import get_asgi_application
from whitenoise import WhiteNoise  # <--- Importante

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from scanner.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    # Envolvemos la app HTTP con WhiteNoise para que capture /static/ bajo ASGI
    "http": WhiteNoise(django_asgi_app),
    "websocket": URLRouter(
        websocket_urlpatterns
    ),
})