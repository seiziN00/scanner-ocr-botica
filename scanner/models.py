import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def default_expiration():
    return timezone.now() + timedelta(hours=settings.IMPORT_SESSION_TTL_HOURS)


# Lista canónica de unidades: la usan el formulario y las plantillas.
UNIDAD_CHOICES = [
    "UNIDAD",
    "TABLETA",
    "FRASCO",
    "BLÍSTER",
    "CAJA",
    "CÁPSULA",
    "SOBRE",
    "TUBO",
    "AMPOLLA",
]


class ImportSession(models.Model):
    """Sesión de importación de un comprobante.

    La sesión pertenece al SERVIDOR. Los dispositivos (móvil / PC)
    son solo clientes que se conectan a ella.
    """

    class Status(models.TextChoices):
        CAPTURING = "capturing", "Capturando fotos"
        PROCESSING = "processing", "Procesando"
        READY = "ready", "Lista para validar"
        CLOSED = "closed", "Cerrada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CAPTURING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(default=default_expiration)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Sesión {str(self.id)[:8]} ({self.get_status_display()})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_available(self) -> bool:
        """Predicado único de acceso: lo usan las vistas HTTP y el WebSocket."""
        return not self.is_expired and self.status != self.Status.CLOSED

    @property
    def items_count(self) -> int:
        return self.items.count()


def scan_image_path(instance: "ScanImage", filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"scans/{instance.session_id}/{instance.position}.{ext}"


def scan_thumb_path(instance: "ScanImage", filename: str) -> str:
    return f"scans/{instance.session_id}/thumb-{instance.position}.jpg"


class ScanImage(models.Model):
    """Fotografía subida de un comprobante (máx. 4 por sesión)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ImportSession, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to=scan_image_path)
    thumb = models.ImageField(upload_to=scan_thumb_path, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]

    def __str__(self) -> str:
        return f"Foto {self.position} de {self.session_id}"


class ProductItem(models.Model):
    """Ítem de producto extraído o ingresado manualmente."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ImportSession, on_delete=models.CASCADE, related_name="items"
    )
    producto = models.CharField(max_length=200)
    cantidad = models.PositiveIntegerField(default=1)
    laboratorio = models.CharField(max_length=120, blank=True)
    lote = models.CharField(max_length=60, blank=True)
    vencimiento = models.CharField(max_length=7, blank=True)  # formato YYYY-MM
    unidad = models.CharField(max_length=20, default="UND")
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self) -> str:
        return f"{self.producto} x{self.cantidad}"

    @property
    def precio_total(self):
        return self.cantidad * self.precio_unitario


class PairingToken(models.Model):
    """Token de emparejamiento de corta duración y un solo uso.

    El QR solo contiene una URL con este token; nunca datos del comprobante.
    """

    token = models.CharField(max_length=64, unique=True, editable=False)
    session = models.ForeignKey(
        ImportSession, on_delete=models.CASCADE, null=True, blank=True,
        related_name="pairing_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def create(cls) -> "PairingToken":
        return cls.objects.create(
            token=secrets.token_urlsafe(16),
            expires_at=timezone.now()
            + timedelta(seconds=settings.PAIRING_TOKEN_TTL_SECONDS),
        )

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def __str__(self) -> str:
        return f"Pairing {self.token[:8]}"
