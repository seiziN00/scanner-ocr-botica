from django import forms

from .models import ProductItem
from .validators import VENCIMIENTO_RE


class ProductItemForm(forms.ModelForm):
    """Validación del lado del servidor para crear/editar ítems."""

    class Meta:
        model = ProductItem
        fields = [
            "producto",
            "cantidad",
            "laboratorio",
            "lote",
            "vencimiento",
            "unidad",
            "precio_unitario",
        ]

    def clean_producto(self):
        value = (self.cleaned_data.get("producto") or "").strip()
        if not value:
            raise forms.ValidationError("El nombre del producto es obligatorio.")
        return value

    def clean_cantidad(self):
        value = self.cleaned_data.get("cantidad")
        if value is None or value < 1:
            raise forms.ValidationError("La cantidad debe ser al menos 1.")
        return value

    def clean_vencimiento(self):
        value = (self.cleaned_data.get("vencimiento") or "").strip()
        if value and not VENCIMIENTO_RE.match(value):
            raise forms.ValidationError("Usa el formato AAAA-MM (ej. 2027-03).")
        return value

    def clean_precio_unitario(self):
        value = self.cleaned_data.get("precio_unitario")
        if value is None or value < 0:
            raise forms.ValidationError("El precio no puede ser negativo.")
        return value
