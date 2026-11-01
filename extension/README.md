# Extensión de Chrome

Captura lo que hace el participante en la aplicación evaluada, muestra las tareas en el panel lateral y entrega todo al servidor local. Es Manifest V3, en JavaScript, **sin empaquetador ni dependencias**: los archivos se cargan tal cual, en el orden del manifiesto.

## Partes

| Parte | Archivos | Dónde corre |
|---|---|---|
| Content scripts | `content/`: los módulos (`capture.js`, `camera.js`, `calibration.js`, `task-end.js`) y `bootstrap.js` | En la pestaña evaluada. Solo arrancan sus módulos si su pestaña es la de la sesión |
| Panel lateral | `panel/` | Panel lateral de Chrome; persiste al navegar |
| Service worker | `worker.js` | Segundo plano: mediador entre panel y pestaña, y envío al servidor |
| Motor de la cámara | `camera/`: `engine.html` (documento *offscreen*), `permission.html` y sus scripts | Documento oculto de la extensión que abre la webcam y persiste al navegar; detalle en `camera/README.md` |
| Librerías de la cámara | `lib/` | MediaPipe Face Landmarker y su modelo; versiones y licencias en `lib/README.md` |
| Utilidades comunes | `common/` | En los tres contextos, según lo que cada uno necesite |
| Configuración | `config.generated.js` | Generada desde `config/shared.json` y `contracts/enums.json`; no se edita |
| Página de prueba | `test-page/` | No es parte de la extensión: se sirve por HTTP para probarla |

## Manifiesto

JSON no admite comentarios, así que el manifiesto se explica aquí.

| Clave | Valor | Por qué |
|---|---|---|
| `permissions` | `sidePanel` | Mostrar el panel lateral |
| | `storage` | `storage.session` guarda el estado de la sesión; `storage.local`, la cola de envío |
| | `tabs` | Conocer la pestaña activa (URL, título y tamaño) al iniciar la sesión y enviarle mensajes |
| | `offscreen` | Crear el documento oculto del motor de la cámara (motivo `USER_MEDIA`) |
| `host_permissions` | `http://127.0.0.1/*` | Hablar con el servidor local sin CORS |
| | `<all_urls>` | Lo exige `tabs.captureVisibleTab` para las capturas de referencia. No agrega advertencias, porque los content scripts ya corren en todas las URL |
| `content_security_policy.extension_pages` | `script-src 'self' 'wasm-unsafe-eval'; object-src 'self'` | MediaPipe corre en WebAssembly, que la política por defecto bloquea en las páginas de la extensión. Solo se permite compilar WebAssembly; el resto queda como la política por defecto |
| `background.service_worker` | `worker.js` | Worker clásico: carga sus utilidades con `importScripts` |
| `action` + `side_panel` | `panel/panel.html` | El ícono abre el panel lateral |
| `content_scripts` | En `<all_urls>`, solo el marco principal, al terminar de cargar la página | Los iframes de otros dominios quedan fuera del alcance |
| | Orden: configuración, utilidades comunes (con `common/modules.js` al final), módulos (`capture`; `camera/strings.js` y `content/camera/zones.js`, que usan los dos siguientes; `camera`, `calibration`, `task-end`) y al final `bootstrap.js` | Cada archivo usa lo que cargaron los anteriores: los módulos se registran en `UX.modules` y `bootstrap.js` los arranca |
| `web_accessible_resources` | — (no se declara) | Las librerías de `lib/` solo las carga el motor de la cámara, que es una página de la extensión. Ninguna página web necesita leerlas |
| `minimum_chrome_version` | `116` | Primera versión con `sidePanel.setPanelBehavior` |

## Utilidades comunes (`UX`)

Cada archivo de `common/` agrega una pieza al espacio de nombres global `UX`. Define una fábrica (`UX.createBatcher`, …) que recibe sus dependencias, y crea la instancia que usa el resto del código (`UX.batcher`) con lo que cargaron los archivos anteriores. Las pruebas usan las fábricas con sustitutos.

| Pieza | Uso | Contextos |
|---|---|---|
| `UX.platform` | Adaptador: **el único** que llama a `chrome.*`. Además de mensajes y almacenamiento: conexiones (`connect`, `onConnect`), documento offscreen (`ensureOffscreen`, `closeOffscreen`), `openExtensionTab`, `extensionUrl` y `onFirstInstall` | Todos |
| `UX.clock.now()` | Marca de tiempo común: `performance.timeOrigin + performance.now()`, en ms | Todos |
| `UX.messages` | `send(type, payload)`, `on(type, handler)`, `sendToTab(tabId, type, payload)` y las constantes `types` del contrato (`types.SESSION_STARTED`…) | Todos |
| `UX.session` | Estado de la sesión activa: `ready`, `get()` (síncrono), `reload()`, `subscribe(fn)`; el panel lo escribe con `start`, `update` y `clear` | Todos |
| `UX.batcher` | `add(type, record)` acumula; `flush()` entrega ya | Content scripts y panel |
| `UX.modules` | Registro de módulos: `register({ name, start(ctx), stop() })` | Content scripts |
| `UX.createSendQueue` | Cola de envío pura con reintentos | Worker |
| `UX.api` | Una función por endpoint del servidor, con el token | Worker y panel |
| `UX.config`, `UX.contracts` | Configuración (`server`, `sending`, `capture`, `camera`) y enumeraciones del contrato | Todos |

Reglas:

- Ningún archivo, salvo `common/platform.js`, llama a `chrome.*`.
- Los valores de enumeraciones salen de `UX.contracts.enums` o de `UX.messages.types`, nunca escritos a mano.
- Los datos de los contratos usan `snake_case`; el resto del JavaScript, `camelCase`.

La forma exacta de cada mensaje, qué mensajes responden y el estado de la sesión están en `contracts/extension-messages.md`.

## Módulos de los content scripts

Cada función que corre en la pestaña evaluada (captura, cámara, calibración, fin de tarea) es un **módulo**: un archivo de `content/` que se registra en `UX.modules` al cargarse. Ningún módulo arranca solo; `bootstrap.js` los inicia y los detiene con la sesión.

### Ciclo de vida

| Momento | Qué hace `bootstrap.js` |
|---|---|
| Carga de una página (también después de cada navegación) | Si hay una sesión activa, pregunta su pestaña (`tab.identify`). Si es la evaluada, llama a `start(ctx)` de cada módulo |
| `session.started` | Llama a `start(ctx)` de cada módulo y responde al panel qué módulos arrancaron y cuáles fallaron |
| `session.closed` | Llama a `stop()` de cada módulo, vacía el acumulador y responde; recién entonces el worker cierra la sesión en el servidor |
| El estado de la sesión se borra sin `session.closed` | Llama a `stop()` de cada módulo |

En las demás pestañas los content scripts se cargan, pero ningún módulo arranca.

### Qué recibe un módulo en `start(ctx)`

El contexto es el mismo para todos los módulos y está congelado:

| Campo | Qué es | Uso típico |
|---|---|---|
| `ctx.clock` | `UX.clock` | `ctx.clock.now()` para el campo `t` de cada registro |
| `ctx.batcher` | `UX.batcher` | `ctx.batcher.add('events', registro)`: el registro debe cumplir su esquema de `contracts/batches/` |
| `ctx.messages` | `UX.messages` | `ctx.messages.on(ctx.messages.types.TASK_STARTED, fn)` para recibir; `ctx.messages.send(...)` para avisar al panel |
| `ctx.session` | Solo lectura: `get()` y `subscribe(fn)` | `ctx.session.get().task_id` para marcar cada registro con la tarea activa |
| `ctx.config` | `UX.config` | Frecuencias y tiempos: `ctx.config.capture.mousemove_hz`, `ctx.config.camera.gaze_hz`… |
| `ctx.contracts` | `UX.contracts` | Versión y enumeraciones del contrato: `ctx.contracts.enums.event_type`… |

Los módulos no escriben el estado de la sesión (solo lo hace el panel) ni llaman a `chrome.*`.

### Reglas de un módulo

- **Errores aislados:** si `start` o `stop` de un módulo fallan, el error se registra en la consola de la pestaña con el nombre del módulo y los demás siguen. `session.started` informa los que fallaron.
- **Arranque rápido:** todos los módulos arrancan a la vez, y ninguno puede contar con que otro ya arrancó. Lo que tarda (por ejemplo, esperar el permiso de la cámara) sigue en segundo plano después de que `start` termina, y se informa con mensajes.
- **Detención segura:** `stop` puede llamarse aunque `start` haya fallado o todavía no haya terminado. Debe quitar todos los oyentes y temporizadores del módulo. Un `stop` que tarda más de 2 s se abandona, para que el cierre de la sesión no quede esperando.
- **Sin estado entre páginas:** después de una navegación completa el módulo se carga de nuevo y vuelve a recibir `start(ctx)`. Lo que deba sobrevivir a la navegación se lee de `ctx.session`.

### Cómo se agrega un módulo

1. Crea el archivo en `content/` (nombre en `kebab-case`), con un encabezado JSDoc que diga qué hace y qué mensajes envía y recibe:

   ```javascript
   /**
    * @file Ejemplo: registra cada vez que la página se oculta.
    *
    * Mensajes: no envía ni recibe; entrega registros `events` con `ctx.batcher`.
    */

   (function (root) {
     'use strict';

     let ctx = null;

     function onHide() {
       // ...construir el registro y entregarlo con ctx.batcher.add('events', registro)
     }

     root.UX.modules.register({
       name: 'page_visibility',
       start(context) {
         ctx = context;
         root.document.addEventListener('visibilitychange', onHide, true);
       },
       stop() {
         root.document.removeEventListener('visibilitychange', onHide, true);
         ctx = null;
       },
     });
   })(globalThis);
   ```

2. Pide al dueño del manifiesto que lo agregue a `content_scripts.js`, **después** de `common/modules.js` y **antes** de `content/bootstrap.js`. Ni `bootstrap.js` ni ningún otro archivo cambian.
3. Agrega sus pruebas en `tests/` (con `node --test`, cargando el archivo y llamando a `start` con un contexto de sustitutos).

El nombre del módulo usa `snake_case`, porque viaja en la respuesta de `session.started`.

### Módulos actuales

| Archivo | Nombre | Estado |
|---|---|---|
| `content/capture.js` | `capture` | Completo: clics, cursor, scroll, selección, formularios, errores de validación, respuesta tras un clic y cambios de pantalla, con filtros de privacidad. Detalle en `content/capture/README.md` |
| `content/camera.js` | `camera` | Completo: registra mirada (con elemento y zona), rostro e intervalos sin datos que llegan del motor de la cámara. Detalle en `camera/README.md` |
| `content/calibration.js` | `calibration` | Completo: capa de 9 puntos de calibración y 5 de validación, con error en píxeles y grados. Detalle en `camera/README.md` |
| `content/task-end.js` | `task_end` | Esqueleto, sin lógica |

## Panel lateral

Separa la lógica de la vista:

| Archivo | Qué hace |
|---|---|
| `panel/controller.js` | **Lógica, sin DOM:** carga los estudios, crea y cierra la sesión, y publica un estado inmutable (`phase`, `studies`, `session`, `tabStatus`, `error`…). Se prueba en Node |
| `panel/panel.js` | **Vista:** dibuja el estado en el HTML y pasa al controlador lo que hace el evaluador. Es el punto de composición del panel |
| `panel/panel.html`, `panel/panel.css` | Estructura y estilos. El HTML no tiene textos: los pone `panel.js` desde `strings.js` (atributos `data-string` y `data-placeholder`) |
| `panel/strings.js` | **Todos** los textos visibles, en español. Los errores y avisos del controlador son códigos que se buscan aquí |

Qué hace hoy:
1. Al abrirse, carga los estudios (`GET /studies`). Si el servidor no responde, lo dice y ofrece reintentar.
2. El evaluador elige estudio, escribe el código del participante y la versión, y elige el modo.
3. **Iniciar sesión:** toma la pestaña activa (debe ser una página `http` o `https`), crea la sesión (`POST /sessions`) con el tamaño de la pestaña y de la pantalla, guarda el estado con `UX.session.start` y envía `session.started`. Si el servidor rechaza un dato, marca el campo.
4. Muestra la sesión en curso y si la pestaña evaluada inició sus módulos.
5. **Cerrar sesión:** vacía su acumulador, envía `session.closed` y borra el estado. El panel no llama a `POST /sessions/{id}/close`: lo hace el worker después de los últimos lotes de la pestaña.

Para extenderlo (modo guiado, SUS, calibración, referencias):
- agrega el estado y las acciones nuevas en el controlador, con sus pruebas;
- dibújalos en `panel.js`;
- pon los textos en `strings.js`.

Para depurarlo, abre su consola con clic derecho sobre el panel → **Inspeccionar**.

## Página de prueba

`test-page/` es un sitio de prueba con todo lo que la captura debe reconocer:
- botones con respuesta inmediata, lenta (2 s) y sin efecto, más un elemento que parece botón y no lo es;
- enlaces internos, a otra página y externos;
- un formulario con validación y campos de distintos tipos, incluida una contraseña;
- un menú desplegable y una búsqueda;
- las regiones `header`, `nav`, `main`, `aside`, `footer` y `role="search"`;
- una tienda de una sola página que cambia de pantalla sin recargar, hasta un "Pedido confirmado".

Los content scripts no corren en las páginas de la extensión (`chrome-extension://…`), así que la página se sirve como un sitio normal, en el puerto `test_page.port` de la configuración:

```bash
python -m scripts.serve_test_page
```

Luego se abre `http://127.0.0.1:8766/`. El puerto sale de `test_page.port`, en `config/shared.json`.

## Cómo viajan los datos

1. Un módulo llama a `ctx.batcher.add('events', record)`. El acumulador anota la sesión activa y entrega cada `sending.interval_ms` (2 s), o antes si junta `sending.max_batch_records`.
2. El worker recibe el mensaje `batch`, lo guarda en `storage.local` y recién entonces responde. Si la respuesta no llega, el acumulador conserva los registros y los reintenta.
3. La cola del worker envía los lotes en orden. Ante un fallo de red o un 5xx, espera 1 s, luego el doble, hasta 30 s (`sending.retry_*`). Un 4xx no se reintenta: se descarta y se registra en la consola del worker.
4. Si Chrome termina el worker, la cola se recupera la próxima vez que despierta.

Los datos llegan **al menos una vez**: si Chrome detiene el worker justo durante una entrega, un lote puede llegar dos veces. El análisis quita los registros duplicados.

Al cerrar la sesión, el panel envía `session.closed`; la pestaña detiene sus módulos y entrega lo que le quedaba, y el worker cierra la sesión **después** de esos lotes.

## Cargarla en Chrome

1. Si cambiaste `config/shared.json` o `contracts/enums.json`, regenera la configuración: `python -m scripts.generate_config`.
2. Abre `chrome://extensions`, activa **Modo de desarrollador** y pulsa **Cargar descomprimida**. Elige la carpeta `extension/`.
3. Después de cambiar el código, pulsa el botón de recargar de la extensión y recarga las pestañas abiertas, para que sus content scripts se actualicen.

Consolas para depurar:
- **Worker:** `chrome://extensions` → SUCA → **Inspeccionar vistas: service worker**.
- **Content scripts:** DevTools de la pestaña → Console → en el selector de contexto (arriba, dice `top`), elige **SUCA**.
- **Panel:** clic derecho sobre el panel → **Inspeccionar**.
- **Motor de la cámara:** `chrome://extensions` → SUCA → **Inspeccionar vistas: camera/engine.html** (aparece mientras hay una sesión activa).

Los content scripts no corren en páginas de Chrome (`chrome://…`) ni en la Chrome Web Store.

## Pruebas

```bash
npm test
```

Ejecuta `node --test` sobre `tests/*.test.js`:
- `fakes.js` simula la plataforma (varios contextos con almacenamiento compartido), los temporizadores y un `chrome` completo;
- `worker.test.js` carga `worker.js` entero, como lo haría Chrome, en un contexto aislado;
- `modules.test.js` y `bootstrap.test.js` prueban el registro y el ciclo de vida de los módulos con la sesión;
- `panel-controller.test.js` prueba la lógica del panel sin DOM;
- `camera-math.test.js`, `camera-engine.test.js` y `camera-content.test.js` prueban la cámara: modelo de mirada, características de los ojos y del rostro, motor, registro en la pestaña, zonas y calibración.
