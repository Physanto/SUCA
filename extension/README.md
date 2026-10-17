# Extensión de Chrome

Captura lo que hace el participante en la aplicación evaluada, muestra las tareas en el panel lateral y entrega todo al servidor local. Es Manifest V3, en JavaScript, **sin empaquetador ni dependencias**: los archivos se cargan tal cual, en el orden del manifiesto.

## Partes

| Parte | Archivos | Dónde corre |
|---|---|---|
| Content scripts | `content/` | En la pestaña evaluada. Solo arrancan sus módulos si su pestaña es la de la sesión |
| Panel lateral | `panel/` | Panel lateral de Chrome; persiste al navegar |
| Service worker | `worker.js` | Segundo plano: mediador entre panel y pestaña, y envío al servidor |
| Utilidades comunes | `common/` | En los tres contextos, según lo que cada uno necesite |
| Configuración | `config.generated.js` | Generada desde `config/shared.json` y `contracts/enums.json`; no se edita |

## Manifiesto

JSON no admite comentarios, así que el manifiesto se explica aquí.

| Clave | Valor | Por qué |
|---|---|---|
| `permissions` | `sidePanel` | Mostrar el panel lateral |
| | `storage` | `storage.session` guarda el estado de la sesión; `storage.local`, la cola de envío |
| | `tabs` | Conocer la pestaña activa (URL y título) al iniciar la sesión y enviarle mensajes |
| `host_permissions` | `http://127.0.0.1/*` | Hablar con el servidor local sin CORS |
| | `<all_urls>` | Lo exige `tabs.captureVisibleTab` para las capturas de referencia. No agrega advertencias, porque los content scripts ya corren en todas las URL |
| `background.service_worker` | `worker.js` | Worker clásico: carga sus utilidades con `importScripts` |
| `action` + `side_panel` | `panel/panel.html` | El ícono abre el panel lateral |
| `content_scripts` | En `<all_urls>`, solo el marco principal, al terminar de cargar la página | Los iframes de otros dominios quedan fuera del alcance |
| | Orden: configuración, utilidades comunes, módulos (`capture`, `camera`, `calibration`, `task-end`) y al final `bootstrap.js` | Cada archivo usa lo que cargaron los anteriores |
| `web_accessible_resources` | `lib/*` | Las librerías de mirada y rostro cargan sus modelos desde la extensión |
| `minimum_chrome_version` | `116` | Primera versión con `sidePanel.setPanelBehavior` |

## Utilidades comunes (`UX`)

Cada archivo de `common/` agrega una pieza al espacio de nombres global `UX`. Define una fábrica (`UX.createBatcher`, …) que recibe sus dependencias, y crea la instancia que usa el resto del código (`UX.batcher`) con lo que cargaron los archivos anteriores. Las pruebas usan las fábricas con sustitutos.

| Pieza | Uso | Contextos |
|---|---|---|
| `UX.platform` | Adaptador: **el único** que llama a `chrome.*` | Todos |
| `UX.clock.now()` | Marca de tiempo común: `performance.timeOrigin + performance.now()`, en ms | Todos |
| `UX.messages` | `send(type, payload)`, `on(type, handler)`, `sendToTab(tabId, type, payload)` y las constantes `types` del contrato (`types.SESSION_STARTED`…) | Todos |
| `UX.session` | Estado de la sesión activa: `ready`, `get()` (síncrono), `reload()`, `subscribe(fn)`; el panel lo escribe con `start`, `update` y `clear` | Todos |
| `UX.batcher` | `add(type, record)` acumula; `flush()` entrega ya | Content scripts y panel |
| `UX.createSendQueue` | Cola de envío pura con reintentos | Worker |
| `UX.api` | Una función por endpoint del servidor, con el token | Worker y panel |
| `UX.config`, `UX.contracts` | Configuración (`server`, `sending`, `capture`, `camera`) y enumeraciones del contrato | Todos |

Reglas:

- Ningún archivo, salvo `common/platform.js`, llama a `chrome.*`.
- Los valores de enumeraciones salen de `UX.contracts.enums` o de `UX.messages.types`, nunca escritos a mano.
- Los datos de los contratos usan `snake_case`; el resto del JavaScript, `camelCase`.

La forma exacta de cada mensaje, qué mensajes responden y el estado de la sesión están en `contracts/extension-messages.md`.

## Cómo viajan los datos

1. Un módulo llama a `UX.batcher.add('events', record)`. El acumulador anota la sesión activa y entrega cada `sending.interval_ms` (2 s), o antes si junta `sending.max_batch_records`.
2. El worker recibe el mensaje `batch`, lo guarda en `storage.local` y recién entonces responde. Si la respuesta no llega, el acumulador conserva los registros y los reintenta.
3. La cola del worker envía los lotes en orden. Ante un fallo de red o un 5xx, espera 1 s, luego el doble, hasta 30 s (`sending.retry_*`). Un 4xx no se reintenta: se descarta y se registra en la consola del worker.
4. Si Chrome termina el worker, la cola se recupera la próxima vez que despierta.

Al cerrar la sesión, el panel no llama al servidor: envía `session.closed` y el worker cierra la sesión **después** de los últimos lotes de la pestaña.

## Cargarla en Chrome

1. Si cambiaste `config/shared.json` o `contracts/enums.json`, regenera la configuración: `python -m scripts.generate_config`.
2. Abre `chrome://extensions`, activa **Modo de desarrollador** y pulsa **Cargar descomprimida**. Elige la carpeta `extension/`.
3. Después de cambiar el código, pulsa el botón de recargar de la extensión y recarga las pestañas abiertas, para que sus content scripts se actualicen.

La consola del worker se abre desde `chrome://extensions` → **Inspeccionar vistas: service worker**. Los content scripts no corren en páginas de Chrome (`chrome://…`) ni en la Chrome Web Store.

## Pruebas

```bash
npm test
```

Ejecuta `node --test` sobre `tests/*.test.js`:
- `fakes.js` simula la plataforma (varios contextos con almacenamiento compartido), los temporizadores y un `chrome` completo;
- `worker.test.js` carga `worker.js` entero, como lo haría Chrome, en un contexto aislado.
