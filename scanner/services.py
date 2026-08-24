"""Servicios del escáner: integración con el LLM y normalización.

La clave del API vive SOLO aquí (backend), cargada desde .env.
El navegador jamás se comunica directamente con el LLM.
"""

from __future__ import annotations

import base64
import io
import json
import re
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from .validators import normalize_vencimiento


class LLMError(Exception):
    """Error con mensaje entendible para el personal de la botica."""


def verify_image(data: bytes) -> bool:
    """Verifica que los bytes sean realmente una imagen válida."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        return True
    except Exception:
        return False


def build_thumbnail(data: bytes, name: str, max_side: int = 480):
    """Genera una miniatura JPEG para la mesa de trabajo (evita bajar
    los originales de varios MB en el celular). None si falla."""
    try:
        from django.core.files.base import ContentFile
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            img.save(buffer, "JPEG", quality=72)
            return ContentFile(buffer.getvalue(), name=name)
    except Exception:
        return None


PROMPT = """Analiza la(s) imagen(es) adjunta(s): son fotografías de una factura o boleta de compra \
de una botica (farmacia) peruana. Las imágenes pueden ser páginas del mismo comprobante.

Extrae TODOS los ítems de productos de la(s) tabla(s) (omite filas de subtotal, IGV, total, \
y columnas de CÓDIGO o PESO si aparecen).

Devuelve ÚNICAMENTE un JSON válido, sin markdown, sin comentarios, con esta estructura exacta:
{"items": [{"producto": "AZITROMICINA 200MG/5ML PPS x 30ML", "cantidad": 6, "laboratorio": "PORTUGAL", "lote": "2057806", "vencimiento": "2029-05", "unidad": "FRASCO", "precio_unitario": 6.16, "precio_total": 36.96}]}

Reglas:
- "vencimiento" SIEMPRE en formato YYYY-MM; si no es visible, usa "".
- Si un dato de texto no aparece, usa ""; si un precio no aparece, usa 0.
- "cantidad" es un entero mayor o igual a 1.
- "unidad" en mayúsculas (TABLETA, CÁPSULA, SOBRE, FRASCO, TUBO, CAJA, AMPOLLA, UND...). Si no aparece, usa "UND".
- No inventes datos que no estén en la imagen.
- No incluyas ningún texto fuera del JSON."""

def _to_data_url(content: bytes, mimetype: str) -> str:
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mimetype};base64,{b64}"


def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON del texto devuelto por el modelo."""
    text = text.strip()
    # quita cercas de markdown si el modelo las incluye
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # el modelo a veces corta la respuesta: intenta cerrar la estructura
            repaired = candidate.rstrip().rstrip(",")
            for suffix in ("}", "]}", "}]}", "\"}]}"):
                try:
                    return json.loads(repaired + suffix)
                except json.JSONDecodeError:
                    continue
    # último recurso: rescata los objetos de ítem completos (son planos)
    salvaged = []
    for chunk in re.findall(r"\{[^{}]*\}", text):
        try:
            salvaged.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    if salvaged:
        return {"items": salvaged}
    raise LLMError(
        "No se pudo interpretar la respuesta del lector automático. "
        "Intenta nuevamente con fotos más nítidas."
    )


def _normalize_item(raw: object, position: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    producto = str(raw.get("producto") or "").strip()[:200]
    if not producto:
        return None

    try:
        cantidad = max(1, int(float(raw.get("cantidad") or 1)))
    except (TypeError, ValueError):
        cantidad = 1

    try:
        precio = Decimal(str(raw.get("precio_unitario") or 0)).quantize(
            Decimal("0.01")
        )
        if precio < 0:
            precio = Decimal("0.00")
    except (InvalidOperation, ValueError):
        precio = Decimal("0.00")

    unidad = str(raw.get("unidad") or "UND").strip().upper()[:20] or "UND"

    return {
        "producto": producto,
        "cantidad": cantidad,
        "laboratorio": str(raw.get("laboratorio") or "").strip()[:120],
        "lote": str(raw.get("lote") or "").strip()[:60],
        "vencimiento": normalize_vencimiento(raw.get("vencimiento")),
        "unidad": unidad,
        "precio_unitario": precio,
        "position": position,
    }


def extract_items(images: list[tuple[bytes, str]]) -> list[dict]:
    """Envía las imágenes al LLM y devuelve ítems normalizados.

    `images` es una lista de tuplas (contenido_bytes, mimetype).
    Lanza LLMError con mensajes amigables ante cualquier fallo.
    """
    if not settings.LLM_API_KEY:
        raise LLMError("El servicio de lectura no está configurado. Avisa al encargado.")

    content: list[dict] = [{"type": "text", "text": PROMPT}]
    for data, mimetype in images:
        content.append(
            {"type": "image_url", "image_url": {"url": _to_data_url(data, mimetype)}}
        )

    payload = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "reasoning": {"enabled": False},
        "temperature": 0,
        # sin esto algunos proveedores cortan el JSON a mitad de camino
        "max_tokens": 6000,
    }

    try:
        response = requests.post(
            settings.LLM_BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise LLMError(
            "El lector automático tardó demasiado en responder. "
            "Revisa tu conexión e inténtalo otra vez."
        )
    except requests.RequestException:
        raise LLMError(
            "No se pudo conectar con el lector automático. "
            "Revisa la conexión a internet e inténtalo otra vez."
        )

    if response.status_code != 200:
        raise LLMError(
            "El lector automático no está disponible en este momento. "
            "Inténtalo de nuevo en unos minutos."
        )

    try:
        text = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError(
            "El lector automático dio una respuesta inesperada. Inténtalo otra vez."
        )

    data = _extract_json(text)
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise LLMError(
            "El lector automático no encontró una lista de productos. "
            "Verifica que las fotos sean del comprobante."
        )

    items = [
        item
        for pos, raw in enumerate(raw_items)
        if (item := _normalize_item(raw, pos)) is not None
    ]
    if not items:
        raise LLMError(
            "No se detectaron productos en las fotos. "
            "Tómalas de nuevo con mejor luz y encuadre."
        )
    return items
