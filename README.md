# Scanner OCR de facturas para botica

MVP mobile-first para digitalizar comprobantes de compra de una botica:
se fotografía la factura con el celular, un LLM extrae los productos en el
servidor y el personal valida/corrige el detalle. El trabajo puede pasarse
de forma opcional a una PC mediante un código QR y continuar ahí de forma
independiente.

## Stack

- Django 6.1 + Channels 4.3 + Daphne (ASGI / WebSockets)
- django-environ (secretos en `.env`)
- HTMX + JavaScript vanilla + CSS vanilla
- SQLite en desarrollo (PostgreSQL para despliegue)
- `uv` para gestión de dependencias

## Uso desde el celular

1. Conecta el celular y la PC a la misma red Wi-Fi.
2. Agrega la IP de la PC a `ALLOWED_HOSTS` en `.env`, ej.:
   `ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50`
3. Abre `http://<IP-de-la-PC>:8000` en el celular.
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
uv run python manage.py test scanner
```

## Continuar en la PC (QR)

1. En el comprobante validado, toca **«Continuar en la PC»** y sigue las
   instrucciones.
2. En la PC abre `/continuar/`, ingresa la contraseña de emparejamiento y
   muestra el QR.
3. Escanea el QR con el celular y confirma el envío.
4. La PC abre el mismo comprobante al instante; el celular puede
   desconectarse sin afectar el trabajo.

## Arquitectura

```
navegador (móvil/PC) ─ HTTP multipart ─► Django ─► LLM (OpenRouter)
        ▲                                  │
        └──── HTMX parciales / JSON ◄──────┘   (el servidor es la source of truth)
        └──── WebSocket: eventos JSON livianos (máx. 2 equipos por sesión)
```

- `scanner/models.py`: `ImportSession` (del servidor, no del navegador),
  `ScanImage`, `ProductItem`, `PairingToken`.
- `scanner/services.py`: integración con el LLM y normalización del JSON.
- `scanner/consumers.py`: WebSocket por sesión (`ws/sesion/<uuid>/`).
- `scanner/views.py`: captura, procesamiento, CRUD de ítems, emparejamiento.
