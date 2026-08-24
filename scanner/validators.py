"""Validadores/normalizadores compartidos entre formularios y servicios.

Única fuente de verdad para el formato de vencimiento (YYYY-MM).
"""

from __future__ import annotations

import re

VENCIMIENTO_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def normalize_vencimiento(raw: object) -> str:
    """Normaliza el vencimiento al formato YYYY-MM; '' si no es interpretable."""
    if raw is None:
        return ""
    value = str(raw).strip()
    if VENCIMIENTO_RE.match(value):
        return value
    # acepta MM/YYYY, MM-YYYY, YYYY/MM
    m = re.match(r"^(0?[1-9]|1[0-2])[-/](\d{4})$", value)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{4})/(0?[1-9]|1[0-2])$", value)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return ""
