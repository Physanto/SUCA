# Mensajes de la extensión

Contrato de los mensajes que intercambian las partes de la extensión. Los nombres de los mensajes están en la enumeración `message_type` de `enums.json`; los campos usan `snake_case`, también en JavaScript.

## Partes que se comunican

| Contexto | Archivos | Dónde corre |
|---|---|---|
| **Panel lateral** | `extension/panel/` | Panel lateral de Chrome; persiste al navegar |
| **Content scripts** | `extension/content/` (`capture.js`, `camera.js`, `calibration.js`, `task-end.js`) | Pestaña de la aplicación evaluada |
| **Service worker** | `extension/worker.js` | Segundo plano de la extensión |

**El service worker es el mediador** entre el panel lateral y la pestaña evaluada:

- **Del panel a la pestaña:** `chrome.runtime.sendMessage` no llega a los content scripts, así que el panel envía al worker y el worker reenvía el mensaje **solo a la pestaña evaluada** de la sesión activa (`tab_id` en el estado de la sesión).
- **De la pestaña al panel:** Chrome entrega el mensaje de un content script a todas las páginas de la extensión, incluido el panel lateral. El worker no lo reenvía: el panel lo recibiría dos veces.
- **Al worker:** `batch`, `screen_capture.request` y `tab.identify` terminan en el worker, que habla con el servidor.

Solo participa la pestaña evaluada. Los content scripts se cargan en todas las pestañas, pero cada uno pregunta su id con `tab.identify` y solo arranca sus módulos si coincide con `tab_id`.

## Forma de todo mensaje

```json
{
  "type": "session.started",
  "payload": { "session_id": 17, "mode": "guided", "study_id": 2 }
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `type` | string | Uno de los valores de `message_type` |
| `payload` | object | Datos del mensaje; su forma depende de `type` |

### Respuestas

`UX.messages.send` devuelve una promesa. La mayoría de los mensajes no tienen respuesta y la promesa se resuelve con `undefined`. Los que responden:

| Mensaje | Responde | Con | Cuándo |
|---|---|---|---|
| `batch` | Worker | `{ "queued": true }` | Después de guardar el lote en la cola persistente (`storage.local`). Si la promesa falla, el lote no quedó guardado y el acumulador lo reintenta |
| `session.started` | Pestaña evaluada (el worker pasa la respuesta al panel) | `{ "started": [...], "failed": [...] }`: nombres de los módulos que arrancaron y de los que fallaron | Después de iniciar sus módulos. Si la pestaña no tiene content scripts (todavía cargando, o una página de Chrome), la promesa se rechaza; la sesión sigue activa y los módulos arrancan cuando la pestaña cargue una página |
| `session.closed` | Worker al panel; pestaña al worker | Al panel, `{ "closing": true }`; al worker, `{ "flushed": true }` (`false` si algún lote quedó para reintentar) | La pestaña responde después de detener sus módulos y vaciar su acumulador; el worker responde después de poner el cierre en la cola |
| `screen_capture.request` | Worker | `{ "capture_id", "file_path" }` | Cuando el servidor guardó la captura |
| `tab.identify` | Worker | `{ "tab_id" }` | De inmediato |

Si el receptor falla, la promesa se rechaza con su mensaje de error.

### Estado de la sesión

Un content script que se carga después de un mensaje (por ejemplo, tras una navegación) no lo recibe. Por eso el estado de la sesión activa vive en `chrome.storage.session` y todos los contextos lo leen con `UX.session`:

```json
{ "session_id": 17, "mode": "guided", "study_id": 2, "tab_id": 412, "task_id": 3 }
```

| Campo | Descripción |
|---|---|
| `session_id`, `mode`, `study_id` | Los de la sesión creada en el servidor |
| `tab_id` | Pestaña evaluada: la activa cuando el panel inició la sesión |
| `task_id` | Tarea activa del modo guiado, o `null` |

Solo el panel lateral lo escribe: `UX.session.start` al iniciar la sesión, `update({ task_id })` al empezar y terminar cada tarea, y `clear` después de cerrarla. No hay sesión activa si el estado es `null`.

## Resumen

| Mensaje | Lo envía | Lo recibe | Datos |
|---|---|---|---|
| `session.started` | Panel lateral | Content scripts (vía worker) | `session_id`, `mode`, `study_id` |
| `session.closed` | Panel lateral | Content scripts (vía worker) | `session_id` |
| `task.started` | Panel lateral | `task-end.js`, `capture.js` (vía worker) | `task_id`, `end_condition` (o `null`) |
| `task.completed` | `task-end.js` | Panel lateral | `task_id`, `ended_by` |
| `calibration.request` | Panel lateral | Cámara (`camera.js`, `calibration.js`) (vía worker) | `type` |
| `calibration.result` | Cámara | Panel lateral | `error_px`, `error_deg`, `accepted` |
| `camera.status` | Cámara | Panel lateral | `status` |
| `screen_capture.request` | Panel lateral | Service worker | `study_id`, `screen` |
| `batch` | Content scripts, panel lateral | Service worker | `session_id`, `type`, `records` |
| `tab.identify` | Content scripts | Service worker | — |

## Detalle de cada mensaje

### `session.started`

Empieza una sesión. El panel lo envía después de crear la sesión en el servidor y guardar el estado con `UX.session.start`. El worker lo reenvía a la pestaña evaluada, que inicia sus módulos y responde con los que arrancaron (`{ "started": [...], "failed": [...] }`).

Después de cada navegación la pestaña carga sus content scripts de nuevo y no recibe este mensaje: `bootstrap.js` lee el estado de la sesión, pregunta su pestaña con `tab.identify` y, si es la evaluada, inicia los módulos por su cuenta.

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | integer | Sesión creada por el servidor (`POST /sessions`) |
| `mode` | string | `session_mode`: `free`, `guided` o `reference` |
| `study_id` | integer | Estudio de la sesión |

```json
{ "type": "session.started", "payload": { "session_id": 17, "mode": "guided", "study_id": 2 } }
```

### `session.closed`

Termina la sesión. **El cierre en el servidor lo hace el worker**, para que ningún lote llegue después:

1. El panel vacía su propio acumulador (`await UX.batcher.flush()`) y envía `session.closed`.
2. El worker lo reenvía a la pestaña evaluada y espera su respuesta. La pestaña detiene sus módulos, vacía su acumulador y responde `{ "flushed": true }`.
3. El worker pone el cierre (`POST /sessions/{id}/close`) en la cola, detrás de los lotes pendientes, y responde al panel.
4. El panel borra el estado con `UX.session.clear()`.

Si la pestaña ya no existe o no responde, el worker cierra igual. El panel no llama a `POST /sessions/{id}/close`.

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | integer | Sesión que se cierra |

```json
{ "type": "session.closed", "payload": { "session_id": 17 } }
```

### `task.started`

El participante presionó Empezar en una tarea del modo guiado. `task-end.js` empieza a revisar la condición final; la captura marca los registros con la tarea.

| Campo | Tipo | Descripción |
|---|---|---|
| `task_id` | integer | Tarea que empieza |
| `end_condition` | object o null | Condición final de la referencia confirmada de la tarea, con la forma de `end_condition` en `reference.schema.json`; `null` si la tarea no tiene referencia |

```json
{
  "type": "task.started",
  "payload": {
    "task_id": 3,
    "end_condition": { "type": "visible_text", "text": "Pedido confirmado" }
  }
}
```

### `task.completed`

`task-end.js` detectó que se cumplió la condición final. El panel lateral cierra la tarea y envía su registro en un lote `tasks`.

| Campo | Tipo | Descripción |
|---|---|---|
| `task_id` | integer | Tarea completada |
| `ended_by` | string | `ended_by`; desde `task-end.js` siempre es `reference` |

Los finales por botón (`done`, `gave_up`) ocurren en el propio panel lateral y no viajan como mensaje.

`task-end.js` solo revisa la condición final, no los pasos obligatorios. Que la tarea termine por `reference` significa que la página llegó al estado final, no que la tarea fue un éxito: el análisis decide el éxito comparando los pasos del participante con los obligatorios de la referencia. Así la comparación de pasos tiene una sola implementación y la tarea termina en el momento real en que el participante llegó al final.

```json
{ "type": "task.completed", "payload": { "task_id": 3, "ended_by": "reference" } }
```

### `calibration.request`

El panel lateral pide una calibración de mirada.

| Campo | Tipo | Descripción |
|---|---|---|
| `type` | string | `calibration_type`: `initial` o `final` |

```json
{ "type": "calibration.request", "payload": { "type": "initial" } }
```

### `calibration.result`

Resultado de la calibración pedida. El módulo de cámara también lo envía al servidor en un lote `calibration`.

| Campo | Tipo | Descripción |
|---|---|---|
| `error_px` | number | Error medio de validación en píxeles CSS |
| `error_deg` | number | Error medio en grados de ángulo visual |
| `accepted` | boolean | Si se aceptó la calibración |

```json
{
  "type": "calibration.result",
  "payload": { "error_px": 112.5, "error_deg": 2.8, "accepted": true }
}
```

### `camera.status`

Estado de la cámara. Se envía al iniciar la cámara y cada vez que el estado cambia. La sesión puede seguir sin cámara.

| Campo | Tipo | Descripción |
|---|---|---|
| `status` | string | `camera_status`: `active`, `no_permission` o `error` |

```json
{ "type": "camera.status", "payload": { "status": "no_permission" } }
```

### `screen_capture.request`

El evaluador pide una captura de pantalla de referencia para los mapas de calor. El worker captura la parte visible de la pestaña evaluada y la envía al servidor (`POST /captures`), sin pasar por la cola: si falla, la respuesta lo informa y el evaluador puede repetirla. Nunca se usa durante sesiones de participantes.

| Campo | Tipo | Descripción |
|---|---|---|
| `study_id` | integer | Estudio al que pertenece la captura |
| `screen` | object | Pantalla capturada, con la forma de `screen` en `common.json` (`url`, `title`) |

```json
{
  "type": "screen_capture.request",
  "payload": { "study_id": 2, "screen": { "url": "https://shop.local/cart", "title": "Carrito" } }
}
```

### `batch`

Registros para el servidor. Normalmente no se envía a mano: lo envía `UX.batcher`. El worker agrega `contract_version`, guarda el lote en la cola persistente y lo entrega al servidor (`POST /sessions/{id}/batches`) en orden y con reintentos. Un error 4xx del servidor no se reintenta: el lote se descarta y se registra en la consola del worker.

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | integer | Sesión a la que pertenecen los registros, anotada al acumularlos. Así un lote llega a su sesión aunque el estado ya se haya borrado |
| `type` | string | `batch_type`: `events`, `gaze`, `face`, `tasks` o `calibration` |
| `records` | array | Registros que cumplen `batches/<type>.schema.json` |

```json
{
  "type": "batch",
  "payload": {
    "session_id": 17,
    "type": "events",
    "records": [
      {
        "t": 1791380123456.2,
        "type": "mousemove",
        "x": 700,
        "y": 410,
        "screen": { "url": "https://shop.local/cart", "title": "Carrito" },
        "task_id": 3
      }
    ]
  }
}
```

### `tab.identify`

Un content script pregunta el id de su pestaña, que no puede conocer por sí mismo. El worker responde con el id de la pestaña que envió el mensaje. `bootstrap.js` lo compara con `tab_id` del estado de la sesión para saber si está en la pestaña evaluada.

Sin datos (`payload` vacío). Respuesta: `{ "tab_id": 412 }`.

```json
{ "type": "tab.identify", "payload": {} }
```

## Versionado de los contratos

Todos los contratos de `contracts/` (enumeraciones, esquemas y estos mensajes) comparten una versión semántica `MAYOR.MENOR.PARCHE`. La versión actual es el valor `default` de `contract_version` en `batch.schema.json`. Cada lote la lleva, y el esquema acepta cualquier versión con la misma versión mayor.

| Cambio | Ejemplos | Versión |
|---|---|---|
| **Corrección** | Descripciones, ejemplos, documentación; nada que cambie qué es válido | Sube PARCHE |
| **Compatible** | Agregar un campo opcional, un valor a una enumeración (un tipo de incidente nuevo, un tipo de evento nuevo), un mensaje nuevo, un tipo de lote nuevo | Sube MENOR |
| **Rompe** | Renombrar o quitar un campo o un mensaje, cambiar el tipo o las unidades de un campo, volver obligatorio un campo opcional, quitar un valor de una enumeración, restringir un rango | Sube MAYOR y cambia el patrón de `contract_version` |

**Cómo se pide un cambio:** se abre un *issue* con la etiqueta `contract` que explique qué se necesita y por qué. El líder hace el cambio, actualiza los datos simulados y avisa a los afectados. Los cambios compatibles se aprueban sin más; los que rompen requieren acuerdo de los afectados.
