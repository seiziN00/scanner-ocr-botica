"""Rate limiting simple sobre el caché de Django.

Ventana fija por clave (IP, etc.). Fail-open: si el caché no responde,
se deja pasar la petición (la disponibilidad manda sobre el límite).
"""

from __future__ import annotations

import hashlib

from django.core.cache import cache


def client_ip(request) -> str:
    """IP del cliente respetando proxy (Railway) si existe."""
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "?")


def hit(key: str, limit: int, window: int) -> bool:
    """Registra un intento. True = permitido, False = límite excedido."""
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    cache_key = f"rl:{digest}"
    try:
        count = cache.get(cache_key)
        if count is None:
            cache.set(cache_key, 1, timeout=window)
            return True
        if count >= limit:
            return False
        # incr no renueva el TTL → la ventana es fija desde el 1er intento
        cache.incr(cache_key)
        return True
    except Exception:
        return True
