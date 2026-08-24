from django.contrib import admin

from .models import ImportSession, PairingToken, ProductItem, ScanImage


class ScanImageInline(admin.TabularInline):
    model = ScanImage
    extra = 0


class ProductItemInline(admin.TabularInline):
    model = ProductItem
    extra = 0


@admin.register(ImportSession)
class ImportSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "items_count", "created_at", "expires_at"]
    list_filter = ["status"]
    inlines = [ScanImageInline, ProductItemInline]


@admin.register(PairingToken)
class PairingTokenAdmin(admin.ModelAdmin):
    list_display = ["token", "session", "created_at", "expires_at", "used_at"]
