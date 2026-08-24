"""Elimina sesiones de importación caducadas y sus archivos de imagen.

Uso:
    uv run python manage.py cleanup_sessions

Pensado para ejecutarse periódicamente (tarea programada / cron).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from scanner.models import ImportSession


class Command(BaseCommand):
    help = "Elimina las sesiones de importación caducadas y sus fotos."

    def handle(self, *args, **options):
        expired = ImportSession.objects.filter(expires_at__lt=timezone.now())
        count = expired.count()
        files = 0
        for session in expired:
            for img in session.images.all():
                img.image.delete(save=False)
                if img.thumb:
                    img.thumb.delete(save=False)
                files += 1
            session.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Se eliminaron {count} sesiones caducadas y {files} fotos."
            )
        )
