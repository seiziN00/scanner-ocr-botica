"""Pruebas del núcleo de la botica: FIFO, integridad de stock, vistas y auth."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Lote, Movimiento, Producto, User, Venta
from .services import (
    StockInsuficiente,
    confirmar_venta,
    descontar_fifo,
    registrar_compra,
    registrar_entrada,
    registrar_movimiento_manual,
)

HOY = timezone.localdate()


def hacer_producto(**kw) -> Producto:
    defaults = {
        "codigo": "P0001",
        "nombre": "Paracetamol",
        "principio_activo": "Paracetamol",
        "concentracion": "500mg",
        "presentacion": "Tableta",
        "stock_minimo": 10,
        "precio_venta": Decimal("0.50"),
        "costo_unitario": Decimal("0.12"),
        "unidades_por_blister": 10,
        "blisters_por_caja": 10,
        "precio_blister": Decimal("4.50"),
        "precio_caja": Decimal("40.00"),
    }
    defaults.update(kw)
    return Producto.objects.create(**defaults)


def hacer_lote(producto, codigo, dias, stock, costo=None) -> Lote:
    return Lote.objects.create(
        producto=producto,
        codigo_lote=codigo,
        fecha_vencimiento=HOY + timedelta(days=dias),
        stock=stock,
        costo_unitario=costo,
    )


class FifoTests(TestCase):
    def setUp(self):
        self.producto = hacer_producto()
        # Tres lotes: el del medio vence primero
        self.l1 = hacer_lote(self.producto, "L-LEJOS", 300, 50)
        self.l2 = hacer_lote(self.producto, "L-CERCA", 30, 20)
        self.l3 = hacer_lote(self.producto, "L-MEDIO", 120, 30)

    def test_descuenta_primero_el_que_vence_antes(self):
        movs = descontar_fifo(
            producto=self.producto, cantidad_base=45, motivo="Venta de prueba"
        )
        self.l1.refresh_from_db()
        self.l2.refresh_from_db()
        self.l3.refresh_from_db()
        # 20 del que vence en 30 días + 25 del que vence en 120
        self.assertEqual(self.l2.stock, 0)
        self.assertEqual(self.l3.stock, 5)
        self.assertEqual(self.l1.stock, 50)
        # Un movimiento por lote afectado, con saldo corrido descendente
        self.assertEqual(len(movs), 2)
        self.assertEqual([m.cantidad for m in movs], [-20, -25])
        self.assertEqual([m.saldo_resultante for m in movs], [80, 55])

    def test_stock_insuficiente_no_deja_cambios_parciales(self):
        with self.assertRaises(StockInsuficiente):
            descontar_fifo(
                producto=self.producto, cantidad_base=101, motivo="Venta imposible"
            )
        self.assertEqual(
            sum(Lote.objects.values_list("stock", flat=True)), 100
        )
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_entrada_reutiliza_lote_existente(self):
        registrar_entrada(
            producto=self.producto,
            codigo_lote="L-CERCA",
            fecha_vencimiento=self.l2.fecha_vencimiento,
            cantidad=10,
            motivo="Compra de prueba",
        )
        self.l2.refresh_from_db()
        self.assertEqual(self.l2.stock, 30)
        mov = Movimiento.objects.latest("id")
        self.assertEqual(mov.tipo, Movimiento.Tipo.ENTRADA)
        self.assertEqual(mov.saldo_resultante, 110)


class VentaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="caja@biovida.pe", password="x")
        self.producto = hacer_producto()
        hacer_lote(self.producto, "L-CERCA", 30, 100)

    def test_confirmar_venta_descuenta_y_referencia(self):
        venta = confirmar_venta(
            items=[{"codigo": "P0001", "tipo_unidad": "CAJA", "cantidad": 1}],
            metodo_pago="yape",
            usuario=self.user,
        )
        # 1 caja = 10 blísters × 10 unidades = 100 unidades base
        self.assertEqual(self.producto.lotes.get().stock, 0)
        item = venta.items.get()
        self.assertEqual(item.cantidad_base, 100)
        self.assertEqual(item.subtotal, Decimal("40.00"))
        self.assertEqual(venta.total, Decimal("40.00"))
        # Movimiento SALIDA con referencia genérica a la venta
        mov = Movimiento.objects.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.SALIDA)
        self.assertEqual(mov.referencia, venta)
        self.assertEqual(mov.usuario, self.user)

    def test_numeracion_de_ticket_es_secuencial(self):
        v1 = confirmar_venta(
            items=[{"codigo": "P0001", "tipo_unidad": "UNIDAD", "cantidad": 1}],
            metodo_pago="efectivo", usuario=self.user,
        )
        v2 = confirmar_venta(
            items=[{"codigo": "P0001", "tipo_unidad": "UNIDAD", "cantidad": 1}],
            metodo_pago="efectivo", usuario=self.user,
        )
        self.assertEqual(v2.numero, v1.numero + 1)
        self.assertEqual(v1.ticket, f"{v1.numero:06d}")

    def test_presentacion_no_vendible_es_rechazada(self):
        producto = hacer_producto(
            codigo="P0002", nombre="Jarabe", unidades_por_blister=0,
            blisters_por_caja=0, precio_blister=None, precio_caja=None,
        )
        hacer_lote(producto, "L-J1", 60, 10)
        with self.assertRaises(Exception):
            confirmar_venta(
                items=[{"codigo": "P0002", "tipo_unidad": "CAJA", "cantidad": 1}],
                metodo_pago="efectivo", usuario=self.user,
            )

    def test_descuento_no_puede_superar_el_total(self):
        with self.assertRaises(Exception):
            confirmar_venta(
                items=[{"codigo": "P0001", "tipo_unidad": "UNIDAD", "cantidad": 1}],
                metodo_pago="efectivo", usuario=self.user,
                descuento=Decimal("99.00"),
            )


class CompraTests(TestCase):
    def test_registrar_compra_crea_lote_y_entrada(self):
        user = User.objects.create_user(email="admin@biovida.pe", password="x")
        producto = hacer_producto()
        compra = registrar_compra(
            proveedor="Farmasalud",
            comprobante="F001-00482",
            usuario=user,
            items=[{
                "producto_id": producto.pk,
                "codigo_lote": "B1042",
                "fecha_vencimiento": HOY + timedelta(days=400),
                "cantidad": 300,
                "costo_unitario": Decimal("0.12"),
            }],
        )
        self.assertEqual(compra.total, Decimal("36.00"))
        lote = producto.lotes.get()
        self.assertEqual(lote.stock, 300)
        mov = Movimiento.objects.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.ENTRADA)
        self.assertEqual(mov.referencia, compra)


class MovimientoManualTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="caja@biovida.pe", password="x")
        self.producto = hacer_producto()
        hacer_lote(self.producto, "L-CERCA", 30, 15)
        hacer_lote(self.producto, "L-LEJOS", 300, 50)

    def test_salida_sin_lote_usa_fifo(self):
        registrar_movimiento_manual(
            producto=self.producto, direccion="salida", motivo_clave="deterioro",
            cantidad=20, usuario=self.user,
        )
        lotes = {l.codigo_lote: l.stock for l in self.producto.lotes.all()}
        self.assertEqual(lotes["L-CERCA"], 0)
        self.assertEqual(lotes["L-LEJOS"], 45)
        # 15 del lote cercano + 5 del lejano = 2 movimientos, ambos MERMA
        movs = Movimiento.objects.all()
        self.assertEqual(movs.count(), 2)
        self.assertTrue(all(m.tipo == Movimiento.Tipo.MERMA for m in movs))

    def test_salida_dirigida_a_un_lote(self):
        registrar_movimiento_manual(
            producto=self.producto, direccion="salida", motivo_clave="vencido",
            cantidad=10, codigo_lote="L-LEJOS", usuario=self.user,
        )
        lotes = {l.codigo_lote: l.stock for l in self.producto.lotes.all()}
        self.assertEqual(lotes["L-CERCA"], 15)
        self.assertEqual(lotes["L-LEJOS"], 40)

    def test_entrada_requiere_lote_y_vencimiento(self):
        with self.assertRaises(Exception):
            registrar_movimiento_manual(
                producto=self.producto, direccion="entrada", motivo_clave="compra",
                cantidad=10, usuario=self.user,
            )


@override_settings(LOGIN_RATE_LIMIT=3, LOGIN_RATE_WINDOW_SECONDS=60)
class VistaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="caja@biovida.pe", password="secreto1")
        self.producto = hacer_producto()
        hacer_lote(self.producto, "L-CERCA", 30, 100)
        # Combinado: debe aparecer al buscar "paracetamol"
        self.algidol = hacer_producto(
            codigo="P0009", nombre="Algidol",
            principio_activo="Paracetamol + Cafeína + Fenilefrina",
        )
        hacer_lote(self.algidol, "L-A1", 150, 75)

    def login(self):
        self.client.force_login(self.user)

    # ---------------------------------------------------------- auth
    def test_vistas_protegidas_redirigen_al_login(self):
        for url_name, args in [
            ("botica:panel", []),
            ("botica:inventario", []),
            ("botica:pos", []),
            ("botica:kardex", [self.producto.pk]),
        ]:
            response = self.client.get(reverse(url_name, args=args))
            self.assertRedirects(
                response,
                f"{reverse('botica:login')}?next={reverse(url_name, args=args)}",
                msg_prefix=url_name,
            )

    def test_login_con_email(self):
        response = self.client.post(
            reverse("botica:login"),
            {"email": "caja@biovida.pe", "password": "secreto1"},
        )
        self.assertRedirects(response, reverse("botica:panel"))

    def test_login_rate_limit(self):
        url = reverse("botica:login")
        for _ in range(3):
            self.client.post(url, {"email": "x@x.pe", "password": "mala"},
                             REMOTE_ADDR="10.9.9.9")
        response = self.client.post(url, {"email": "x@x.pe", "password": "mala"},
                                    REMOTE_ADDR="10.9.9.9")
        self.assertEqual(response.status_code, 429)

    # ---------------------------------------------------------- búsqueda
    def test_busqueda_incluye_combinados_por_principio_activo(self):
        self.login()
        response = self.client.get(reverse("botica:inventario_filas"), {"q": "paracetamol"})
        html = response.content.decode()
        self.assertIn("Paracetamol", html)
        self.assertIn("Algidol", html)  # combinado encontrado por principio activo

    def test_pos_buscar_devuelve_data_attributes(self):
        self.login()
        response = self.client.get(reverse("botica:pos_buscar"), {"q": "paracetamol"})
        html = response.content.decode()
        self.assertIn('data-code="P0001"', html)
        self.assertIn('data-p-caja="40.00"', html)
        self.assertIn('data-s-blis="10"', html)  # 100 uds ÷ 10 por blíster

    # ---------------------------------------------------------- checkout
    def test_checkout_descuenta_stock_fifo(self):
        self.login()
        payload = {
            "metodo": "efectivo",
            "descuento": 0,
            "items": [{"codigo": "P0001", "tipo_unidad": "BLISTER", "cantidad": 2}],
        }
        response = self.client.post(
            reverse("botica:checkout"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], "9.00")  # 2 blísters × 4.50
        # 2 blísters = 20 unidades base descontadas
        self.assertEqual(self.producto.lotes.get().stock, 80)
        mov = Movimiento.objects.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.SALIDA)
        self.assertEqual(mov.cantidad, -20)

    def test_checkout_rechaza_carrito_vacio(self):
        self.login()
        response = self.client.post(
            reverse("botica:checkout"),
            data=json.dumps({"metodo": "yape", "items": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_checkout_stock_insuficiente_no_vende(self):
        self.login()
        payload = {
            "metodo": "efectivo",
            "items": [{"codigo": "P0001", "tipo_unidad": "UNIDAD", "cantidad": 999}],
        }
        response = self.client.post(
            reverse("botica:checkout"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Stock insuficiente", response.json()["error"])
        self.assertEqual(Venta.objects.count(), 0)
        self.assertEqual(self.producto.lotes.get().stock, 100)

    # ---------------------------------------------------------- kardex
    def test_kardex_muestra_lotes_y_resumen(self):
        self.login()
        confirmar_venta(
            items=[{"codigo": "P0001", "tipo_unidad": "UNIDAD", "cantidad": 5}],
            metodo_pago="efectivo", usuario=self.user,
        )
        response = self.client.get(reverse("botica:kardex", args=[self.producto.pk]))
        html = response.content.decode()
        self.assertIn("L-CERCA", html)
        self.assertIn("Venta Comercial", html)
        self.assertIn("−5", html)

        resumen = self.client.get(
            reverse("botica:kardex_resumen", args=[self.producto.pk]),
            {"periodo": "30d"},
        )
        self.assertIn("−5", resumen.content.decode())

    def test_movimiento_manual_por_http(self):
        self.login()
        response = self.client.post(
            reverse("botica:movimiento"),
            {
                "producto": self.producto.pk,
                "tipo": "salida",
                "motivo": "deterioro",
                "cantidad": 10,
                "lote": "",
                "vencimiento": "",
                "observacion": "Frasco roto",
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("movimientoRegistrado", response["HX-Trigger"])
        self.assertEqual(self.producto.lotes.get().stock, 90)
        mov = Movimiento.objects.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.MERMA)
        self.assertIn("Frasco roto", mov.motivo)

    def test_panel_kpis_cuenta_ventas_del_rango(self):
        self.login()
        confirmar_venta(
            items=[{"codigo": "P0001", "tipo_unidad": "UNIDAD", "cantidad": 2}],
            metodo_pago="efectivo", usuario=self.user,
        )
        response = self.client.get(reverse("botica:panel_kpis"), {"rango": "hoy"})
        html = response.content.decode()
        self.assertIn("S/ 1.00", html)  # 2 × 0.50
        self.assertIn("hx-swap-oob", html)  # pills actualizadas out-of-band
