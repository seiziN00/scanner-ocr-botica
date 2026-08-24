"""Difusión de eventos en tiempo real hacia los dispositivos conectados.

Los WebSockets solo transportan EVENTOS livianos (JSON). Las imágenes
se suben por HTTP multipart y el estado canónico se obtiene por HTTP.
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def session_group(session_id) -> str:
    return f"session_{session_id}"


def broadcast(session_id, event: str, data: dict | None = None) -> None:
    """Envía un evento JSON a todos los dispositivos de la sesión."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        session_group(session_id),
        {
            "type": "session.event",
            "session_id": str(session_id),
            "event": event,
            "data": data or {},
        },
    )
