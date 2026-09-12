"""Consumidores WebSocket del scanner.

* ``SessionConsumer``  — eventos JSON livianos (máx. 2 equipos por sesión).
* ``OcrStreamConsumer`` — la app móvil EMPUJA ítems en JSON; los clientes
  (desktop con htmx-ext ``ws``) reciben ``<tr>`` HTML listo para append,
  con el conteo/total actualizados vía ``hx-swap-oob``.
"""

from __future__ import annotations

import asyncio
import collections
import json
import time
from decimal import Decimal

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from django.conf import settings
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Sum
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string
from django.utils.html import format_html

from .events import session_group
from .forms import ProductItemForm
from .models import ImportSession
from .templatetags.scanner_extras import soles

MAX_DEVICES_PER_SESSION = 2


class SessionConsumer(AsyncJsonWebsocketConsumer):
    # Conteo en memoria del proceso (MVP: un solo proceso Daphne).
    _connections: dict[str, set[str]] = {}
    _lock = asyncio.Lock()

    async def connect(self):
        self.session_id = str(self.scope["url_route"]["kwargs"]["session_id"])
        self.group_name = session_group(self.session_id)

        info = await self._get_session_info()
        if info is None:
            # aceptar primero: así el navegador sí recibe el código de cierre
            await self.accept()
            await self.send_json(
                {
                    "type": "error",
                    "session_id": self.session_id,
                    "data": {"code": "session_unavailable"},
                }
            )
            await self.close(code=4404)
            return

        async with SessionConsumer._lock:
            channels = SessionConsumer._connections.setdefault(self.group_name, set())
            over_limit = (
                self.channel_name not in channels
                and len(channels) >= MAX_DEVICES_PER_SESSION
            )
            if not over_limit:
                channels.add(self.channel_name)
                device_count = len(channels)

        if over_limit:
            # aceptar primero: así el navegador sí recibe el código de cierre
            await self.accept()
            await self.send_json(
                {
                    "type": "error",
                    "session_id": self.session_id,
                    "data": {
                        "code": "max_devices",
                        "max": MAX_DEVICES_PER_SESSION,
                    },
                }
            )
            await self.close(code=4429)
            return

        # avisar a los que YA estaban conectados (antes de unirnos al grupo,
        # para que el propio dispositivo no reciba su propio evento)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "session.event",
                "session_id": self.session_id,
                "event": "device_connected",
                "data": {"devices": device_count},
            },
        )
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.send_json(
            {
                "type": "session_state",
                "session_id": self.session_id,
                "data": {
                    "status": info["status"],
                    "items_count": info["items_count"],
                    "devices": device_count,
                },
            }
        )

    async def disconnect(self, close_code):
        async with SessionConsumer._lock:
            channels = SessionConsumer._connections.get(self.group_name, set())
            channels.discard(self.channel_name)
            device_count = len(channels)
            if not channels:
                SessionConsumer._connections.pop(self.group_name, None)
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            if device_count:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "session.event",
                        "session_id": self.session_id,
                        "event": "device_disconnected",
                        "data": {"devices": device_count},
                    },
                )
        except Exception:
            pass

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def session_event(self, event):
        await self.send_json(
            {
                "type": event["event"],
                "session_id": event["session_id"],
                "data": event["data"],
            }
        )

    @database_sync_to_async
    def _get_session_info(self) -> dict | None:
        """Lee la sesión en hilo síncrono; None si no existe o no está disponible."""
        try:
            session = ImportSession.objects.get(pk=self.session_id)
        except ImportSession.DoesNotExist:
            return None
        if not session.is_available:
            return None
        return {
            "status": session.status,
            "items_count": session.items.count(),
        }


class OcrStreamConsumer(AsyncWebsocketConsumer):
    """ws/ocr/<session_id>/ — stream de ítems OCR.

    La app móvil envía frames JSON::

        {"producto": "Paracetamol 500mg", "cantidad": 300,
         "precio_unitario": 0.12, "unidad": "TAB", "lote": "B1042",
         "vencimiento": "2027-03", "laboratorio": "Medifarma"}

    El servidor valida con ``ProductItemForm``, persiste el ítem y
    difunde a todos los clientes del grupo UN frame de texto con el
    ``<tr>`` renderizado + fragmentos ``hx-swap-oob`` (conteo y total),
    para que el desktop los anexe con la extensión ws de HTMX.

    Seguridad: la sesión debe seguir disponible (expira a las 24 h, igual
    que el resto del flujo) y hay rate limiting por conexión.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stamps: collections.deque[float] = collections.deque()

    # ------------------------------------------------------------ conexión

    async def connect(self):
        self.session_id = str(self.scope["url_route"]["kwargs"]["session_id"])
        self.group_name = f"ocr_{self.session_id}"

        if not await self._session_disponible():
            await self.accept()  # aceptar primero: el cliente ve el cierre
            await self.close(code=4404)
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            pass

    # ------------------------------------------------------------ mensajes

    def _permitido(self) -> bool:
        """Ventana deslizante por conexión (en memoria del proceso)."""
        limit = settings.OCR_WS_RATE_LIMIT
        window = settings.OCR_WS_RATE_WINDOW_SECONDS
        now = time.monotonic()
        while self._stamps and now - self._stamps[0] > window:
            self._stamps.popleft()
        if len(self._stamps) >= limit:
            return False
        self._stamps.append(now)
        return True

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if not self._permitido():
            await self.close(code=4429)
            return
        try:
            data = json.loads(text_data or "")
        except json.JSONDecodeError:
            return
        html = await self._persistir_y_renderizar(data)
        if html is None:
            # Aviso visible sin romper la tabla: fila de error efímera
            await self.send(
                text_data='<tr><td colspan="8" class="empty-cell">'
                "Payload OCR inválido o sesión expirada.</td></tr>"
            )
            return
        await self.channel_layer.group_send(
            self.group_name, {"type": "ocr.row", "html": html}
        )

    async def ocr_row(self, event):
        """Cada frame es SOLO HTML (la extensión ws de HTMX lo swappea)."""
        await self.send(text_data=event["html"])

    # ------------------------------------------------------------ datos

    @database_sync_to_async
    def _session_disponible(self) -> bool:
        try:
            return ImportSession.objects.get(pk=self.session_id).is_available
        except ImportSession.DoesNotExist:
            return False

    @database_sync_to_async
    def _persistir_y_renderizar(self, data) -> str | None:
        if not isinstance(data, dict):
            return None
        try:
            session = ImportSession.objects.get(pk=self.session_id)
        except ImportSession.DoesNotExist:
            return None
        if not session.is_available:
            return None

        payload = {
            "producto": str(data.get("producto", ""))[:200],
            "cantidad": data.get("cantidad", 1),
            "unidad": str(data.get("unidad", "UND"))[:20],
            "precio_unitario": data.get("precio_unitario", 0),
            "laboratorio": str(data.get("laboratorio", ""))[:120],
            "lote": str(data.get("lote", ""))[:60],
            "vencimiento": str(data.get("vencimiento", ""))[:7],
        }
        form = ProductItemForm(payload)
        if not form.is_valid():
            return None

        item = form.save(commit=False)
        item.session = session
        item.position = (session.items.aggregate(m=Max("position"))["m"] or 0) + 1
        item.save()

        # Conteo y total actualizados para los fragmentos OOB del footer
        agg = session.items.aggregate(
            n=Count("id"),
            t=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("cantidad") * F("precio_unitario"),
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    )
                ),
                Decimal("0"),
            ),
        )
        row_html = render_to_string(
            "scanner/partials/ocr_row.html",
            {"item": item, "session_id": session.id},
        )
        count_html = format_html(
            '<em id="ocr-items-count" hx-swap-oob="true">{} ítem{}</em>',
            agg["n"],
            "" if agg["n"] == 1 else "s",
        )
        total_html = format_html(
            '<strong id="ocr-items-total" hx-swap-oob="true">{}</strong>',
            soles(agg["t"]),
        )
        return row_html + count_html + total_html
