"""Vistas de la botica (un módulo por pantalla) + helpers compartidos."""

from django.shortcuts import render


def es_htmx(request) -> bool:
    """True si la petición viene de HTMX (cabecera HX-Request)."""
    return request.headers.get("HX-Request") == "true"


def render_app(request, partial: str, context: dict, *, status: int = 200):
    """Renderiza el partial solo (navegación HTMX) o la página completa.

    Navegación SPA: los links del sidebar hacen ``hx-get`` a la MISMA url
    real; si la petición es HTMX se devuelve solo el partial para swappear
    ``#app-content``, y si es acceso directo (refresh, sin JS, URL pegada)
    se devuelve ``app.html`` (base + partial embebido).
    """
    if es_htmx(request):
        return render(request, partial, context, status=status)
    return render(
        request,
        "botica/app.html",
        {**context, "content_partial": partial},
        status=status,
    )
