"""Consumidor WebSocket: sincronización en tiempo real por sesión.

Máximo 2 dispositivos simultáneos por sesión (móvil + PC).
El servidor sigue siendo la fuente de verdad; aquí solo se notifican
eventos para que cada cliente pida el estado actualizado por HTTP.
"""

from __future__ import annotations

import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .events import session_group
from .models import ImportSession

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
