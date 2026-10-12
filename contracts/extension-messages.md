# Mensajes de la extensión

Contrato de los mensajes que intercambian las partes de la extensión. Los nombres de los mensajes están en la enumeración `message_type` de `enums.json`; los campos usan `snake_case`, también en JavaScript.

## Partes que se comunican

| Contexto | Archivos | Dónde corre |
|---|---|---|
| **Panel lateral** | `extension/panel/` | Panel lateral de Chrome; persiste al navegar |
| **Content scripts** | `extension/content/` (`capture.js`, `camera.js`, `calibration.js`, `task-end.js`) | Pestaña de la aplicación evaluada |
| **Service worker** | `extension/worker.js` | Segundo plano de la extensión |

**El service worker es el mediador.** El panel lateral y los content scripts nunca se hablan directamente: todo mensaje pasa por el worker, que lo reenvía al destino.

- Del panel a los content scripts: el worker lo reenvía a la pestaña evaluada de la sesión activa.
- De los content scripts al panel: el worker lo reenvía al panel lateral.
- `batch` y `screen_capture.request` terminan en el worker, que habla con el servidor.

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

Los mensajes no esperan respuesta. Un content script que se carga después de un mensaje (por ejemplo, tras una navegación) no lo recibe: obtiene el estado actual de la sesión con `UX.session`, que vive en `chrome.storage.session`. Por eso la tarea activa también está en ese estado y no solo en los mensajes.

## Resumen

| Mensaje | Lo envía | Lo recibe | Datos |
|---|---|---|---|
| `session.started` | Panel lateral | Content scripts | `session_id`, `mode`, `study_id` |
| `session.closed` | Panel lateral | Content scripts | `session_id` |
| `task.started` | Panel lateral | `task-end.js`, `capture.js` | `task_id`, `end_condition` (o `null`) |
| `task.completed` | `task-end.js` | Panel lateral | `task_id`, `ended_by` |
| `calibration.request` | Panel lateral | Cámara (`camera.js`, `calibration.js`) | `type` |
| `calibration.result` | Cámara | Panel lateral | `error_px`, `error_deg`, `accepted` |
| `camera.status` | Cámara | Panel lateral | `status` |
| `screen_capture.request` | Panel lateral | Service worker | `study_id`, `screen` |
| `batch` | Content scripts, panel lateral | Service worker | `type`, `records` |

## Detalle de cada mensaje

### `session.started`

Empieza una sesión. Los content scripts inician sus módulos.

| Campo | Tipo | Descripción |
|---|---|---|
| `session_id` | integer | Sesión creada por el servidor (`POST /sessions`) |
| `mode` | string | `session_mode`: `free`, `guided` o `reference` |
| `study_id` | integer | Estudio de la sesión |

```json
{ "type": "session.started", "payload": { "session_id": 17, "mode": "guided", "study_id": 2 } }
```

### `session.closed`

Termina la sesión. Los content scripts detienen sus módulos y entregan lo que tengan acumulado.

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

El evaluador pide una captura de pantalla de referencia para los mapas de calor. El worker captura la pestaña evaluada y la envía al servidor (`POST /captures`). Nunca se usa durante sesiones de participantes.

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

Registros para el servidor. Normalmente no se envía a mano: lo envía `UX.batcher`. El worker agrega `contract_version`, los pone en cola y los entrega al servidor (`POST /sessions/{id}/batches`) con reintentos.

| Campo | Tipo | Descripción |
|---|---|---|
| `type` | string | `batch_type`: `events`, `gaze`, `face`, `tasks` o `calibration` |
| `records` | array | Registros que cumplen `batches/<type>.schema.json` |

```json
{
  "type": "batch",
  "payload": {
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

## Versionado de los contratos

Todos los contratos de `contracts/` (enumeraciones, esquemas y estos mensajes) comparten una versión semántica `MAYOR.MENOR.PARCHE`. La versión actual es el valor `default` de `contract_version` en `batch.schema.json`. Cada lote la lleva, y el esquema acepta cualquier versión con la misma versión mayor.

| Cambio | Ejemplos | Versión |
|---|---|---|
| **Corrección** | Descripciones, ejemplos, documentación; nada que cambie qué es válido | Sube PARCHE |
| **Compatible** | Agregar un campo opcional, un valor a una enumeración (un tipo de incidente nuevo, un tipo de evento nuevo), un mensaje nuevo, un tipo de lote nuevo | Sube MENOR |
| **Rompe** | Renombrar o quitar un campo o un mensaje, cambiar el tipo o las unidades de un campo, volver obligatorio un campo opcional, quitar un valor de una enumeración, restringir un rango | Sube MAYOR y cambia el patrón de `contract_version` |

**Cómo se pide un cambio:** se abre un *issue* con la etiqueta `contract` que explique qué se necesita y por qué. El líder hace el cambio, actualiza los datos simulados y avisa a los afectados. Los cambios compatibles se aprueban sin más; los que rompen requieren acuerdo de los afectados.
