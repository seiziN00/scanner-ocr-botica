# Botica Bio Vida — Sistema de cabina + Scanner OCR

Sistema de gestión de botica (farmacia) con dos módulos:

- **`botica`** (raíz `/`): sistema de cabina — panel, punto de venta (POS),
  inventario y kardex. Requiere login (usuario con email).
- **`scanner`** (`/scanner/`): MVP mobile-first para digitalizar comprobantes
  de compra — se fotografía la factura con el celular, un LLM extrae los
  productos y el personal valida/corrige el detalle. El trabajo puede pasarse
  a una PC mediante un código QR.

## Stack

- Django 6.1 + Channels 4.3 + Daphne (ASGI / WebSockets)
- django-environ (secretos en `.env`)
- HTMX 2.x + JavaScript vanilla + CSS vanilla
- SQLite en desarrollo (PostgreSQL para despliegue)
- `uv` para gestión de dependencias

## Autenticación (botica)

Usuario personalizado con **email** como credencial (sin username). Todas las
vistas de `botica` requieren `@login_required` excepto `/login/`. El login
tiene rate limiting por IP (`LOGIN_RATE_LIMIT` intentos por
`LOGIN_RATE_WINDOW_SECONDS`).

```powershell
# crear usuario de cabina
uv run python manage.py createsuperuser
# o con el seed de demostración:
uv run python manage.py seed_botica --email caja@biovida.pe --password clave123
```

## Modelo de dominio (botica)

Tres pilares:

1. **`Producto`** — el "qué tengo" agregado (catálogo, precios por
   presentación, factores de equivalencia unidad/blíster/caja).
2. **`Lote`** — la existencia física (código de lote, vencimiento, stock).
3. **`Movimiento`** — el kardex: pista de auditoría con `saldo_resultante`
   (saldo corrido) y referencia genérica a `Venta`/`Compra`.

Las transacciones (`Venta`/`Compra`) disparan movimientos automáticos vía
`botica/services.py`. Toda deducción de stock usa `select_for_update()` +
`F()` dentro de `transaction.atomic()`; las ventas descuentan con **FIFO/FEFO**
(el lote que vence primero sale primero).

## HTMX (botica)

- Navegación SPA: los links del sidebar hacen `hx-get` a la URL real y
  swappean `#app-content`; acceso directo renderiza la página completa
  (`views.render_app`).
- Búsquedas y filtros son server-side y swappean **solo** la región afectada
  (`#inv-rows`, `#pos-results`, `#venc-rows`, `#kdx-movs`), nunca todo el
  `#app-content`, para no perder el foco.
- Estado global (conteos de pills, cabecera del kardex) se actualiza con
  `hx-swap-oob`.
- Tras registrar un movimiento o cobrar, el servidor emite `HX-Trigger`
  (`movimientoRegistrado`) o el cliente dispara `refreshPos`; las regiones
  escuchan con `hx-trigger="... from:body"` y se recargan solas.

## Uso desde el celular (scanner)

1. Conecta el celular y la PC a la misma red Wi-Fi.
2. Agrega la IP de la PC a `ALLOWED_HOSTS` en `.env`, ej.:
   `ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50`
3. Abre `http://<IP-de-la-PC>:8000/scanner/` en el celular.
4. **Cámara en red local (HTTP):** los navegadores exigen HTTPS para
   `getUserMedia`. Para pruebas locales puedes:
   - usar el botón **«Subir desde galería»** o
   - en Chrome Android: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
     agregando `http://<IP-de-la-PC>:8000`, o
   - servir con HTTPS (mkcert + daphne) en una fase posterior.

Para despliegue se usará Railway + PostgreSQL + Redis + Daphne como ASGI.

## Mantenimiento

Las sesiones caducan a las 24 h. Para eliminar sesiones caducadas y sus fotos
(programar como tarea periódica):

```powershell
uv run python manage.py cleanup_sessions
```

o presionar el botón "Terminar trabajo"

## Pruebas

```powershell
uv run python manage.py test            # todo
uv run python manage.py test botica     # sistema de cabina
uv run python manage.py test scanner    # scanner OCR
```

## Continuar en la PC (QR)

1. En el comprobante validado, toca **«Continuar en la PC»** y sigue las
   instrucciones.
2. En la PC abre `/scanner/continuar/`, ingresa la contraseña de emparejamiento
   y muestra el QR.
3. Escanea el QR con el celular y confirma el envío.
4. La PC abre el mismo comprobante al instante; el celular puede
   desconectarse sin afectar el trabajo.

## Arquitectura

```
navegador (móvil/PC) ─ HTTP multipart ─► Django ─► LLM (OpenRouter)
        ▲                                  │
        └──── HTMX parciales / JSON ◄──────┘   (el servidor es la source of truth)
        └──── WebSocket ws/sesion/<id>/: eventos JSON (máx. 2 equipos)
        └──── WebSocket ws/ocr/<id>/: la app móvil empuja ítems JSON;
              el desktop recibe <tr> HTML (htmx-ext ws) + totales OOB
```

- `botica/models.py`: `User`, `Producto`, `Lote`, `Movimiento`, `Venta`,
  `VentaItem`, `Compra`, `CompraItem`, `Secuencia`.
- `botica/services.py`: FIFO/FEFO, confirmación de venta/compra, movimientos
  manuales — toda la lógica de stock con bloqueos de concurrencia.
- `botica/views/`: `auth`, `dasboard`, `inventario`, `kardex`, `pos`.
- `scanner/models.py`: `ImportSession` (del servidor, no del navegador),
  `ScanImage`, `ProductItem`, `PairingToken`.
- `scanner/services.py`: integración con el LLM y normalización del JSON.
- `scanner/consumers.py`: `SessionConsumer` (`ws/sesion/<uuid>/`) y
  `OcrStreamConsumer` (`ws/ocr/<uuid>/`, rate-limited, sesión de 24 h).
- `scanner/views.py`: captura, procesamiento, CRUD de ítems, emparejamiento.
