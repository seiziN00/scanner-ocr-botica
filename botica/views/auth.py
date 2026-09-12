"""Autenticación: login con email (única vista pública) + logout por POST."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from ..ratelimit import client_ip, hit


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("botica:panel")

    error = None
    bloqueado = False

    if request.method == "POST":
        clave = f"login:{client_ip(request)}"
        permitido = hit(
            clave,
            settings.LOGIN_RATE_LIMIT,
            settings.LOGIN_RATE_WINDOW_SECONDS,
        )
        if not permitido:
            bloqueado = True
        else:
            email = request.POST.get("email", "").strip()
            password = request.POST.get("password", "")
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                destino = request.GET.get("next", "")
                if url_has_allowed_host_and_scheme(
                    destino, allowed_hosts={request.get_host()}
                ):
                    return redirect(destino)
                return redirect("botica:panel")
            error = "Correo o contraseña incorrectos."

    return render(
        request,
        "botica/login.html",
        {"error": error, "bloqueado": bloqueado},
        status=429 if bloqueado else 200,
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("botica:login")
