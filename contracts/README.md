# Contratos

Formatos de datos, valores permitidos y mensajes que conectan las piezas del sistema. Cada módulo solo necesita conocer estos contratos, no el código de los demás.

## Archivos

| Archivo | Contenido |
|---|---|
| `enums.json` | **Única fuente** de los valores permitidos (tipos de lote, de evento, de incidente, zonas de mirada…) |
| `common.json` | Tipos compartidos: marca de tiempo, identificador, pantalla, datos vacíos |
| `batch.schema.json` | Sobre de un lote: `contract_version`, `type`, `records` |
| `batches/<tipo>.schema.json` | Un registro de cada tipo de lote: `events`, `gaze`, `face`, `tasks`, `calibration` |
| `element.schema.json` | Descriptor de un elemento de la página |
| `reference.schema.json` | Referencia de una tarea: pasos, condiciones candidatas, condición final y pasos obligatorios |
| `study.schema.json` | Definición de un estudio en `studies/*.yaml`: sistema evaluado y tareas en orden |
| `extension-messages.md` | Mensajes entre las partes de la extensión y reglas de versionado |
| `examples/` | Un ejemplo válido por esquema y ejemplos inválidos |

Los esquemas usan JSON Schema draft 2020-12. Cada `$id` empieza por `https://suca.local/contracts/`: es solo un identificador para resolver los `$ref` entre archivos y nunca se descarga.

## Convenciones

- Claves y valores en inglés y `snake_case`, en todos los lenguajes. `description` en español en cada esquema y cada propiedad.
- **Las enumeraciones solo se definen en `enums.json`.** Los esquemas las usan con `$ref` (`"$ref": "enums.json#/$defs/event_type"`), y el código Python las lee con `shared.contracts.enums()`. Ningún valor se escribe a mano.
- Las marcas de tiempo son milisegundos desde 1970 (`performance.timeOrigin + performance.now()`); se rechazan valores en segundos.
- Los registros no admiten campos que no estén en su esquema (`additionalProperties: false`). Esto también protege la privacidad: un `field_change` con un campo `value` se rechaza.
- Cuando un campo obligatorio admite `null`, `null` indica que el dato no existe (por ejemplo, `task_id` fuera de una tarea o `id` en un elemento sin id); el campo no se omite.

### Intervalos sin datos de cámara

Hay dos casos distintos:

1. **La cámara funciona pero no hay rostro o mirada:** se siguen enviando muestras, con `valid: false` en `gaze` y `face_detected: false` en `face`.
2. **La cámara no produce datos** (una carga de página la reinicia, se negó el permiso, falla): el módulo de cámara envía un evento `camera_gap` en un lote `events`, con `t` = inicio del intervalo y `data` = `{ "t_end", "reason" }`. `t_end` es `null` si la cámara no volvió antes de cerrar la sesión; `reason` es `navigation`, `no_permission` o `error`.

Así, la ausencia de muestras entre dos marcas de tiempo nunca es ambigua. Los detectores que cuentan eventos de interacción (por ejemplo, la pausa prolongada) deben excluir `camera_gap`.

## Validar en Python

Toda validación pasa por `shared/contracts.py`, el único módulo que usa jsonschema:

```python
from shared.contracts import enums, validate

errors = validate("batch", document)       # [] si es válido
for error in errors:
    print(error.path, error.message)         # ('records', 3, 'x') "'x' is a required property"

enums()["incident_type"]                     # ('rage_click', 'dead_click', ...)
```

`validate(kind, document)` acepta como `kind` el nombre de cualquier archivo `*.schema.json` sin la extensión: `batch`, `events`, `gaze`, `face`, `tasks`, `calibration`, `element`, `reference`, `study`.

## Ejemplos

`examples/<kind>.valid.json` es un documento válido; `examples/<kind>.invalid.<problema>.json` tiene exactamente el problema que indica su nombre. `batch.valid.json` contiene un evento de cada tipo y sirve como referencia para la captura.

## Pruebas

```bash
pytest tests/contracts
```

Las pruebas validan todos los ejemplos (los inválidos deben fallar con el error esperado) y comprueban que los esquemas y `enums.json` son coherentes: cada tipo de lote tiene su esquema, cada tipo de evento tiene sus reglas y ningún esquema define valores propios.

## Cómo extender

| Cambio | Pasos |
|---|---|
| Nuevo valor de una enumeración (un tipo de incidente, por ejemplo) | Agregarlo en `enums.json` |
| Nuevo tipo de evento | Agregarlo a `event_type` y agregar su rama en `allOf` de `batches/events.schema.json`, con sus campos obligatorios y la forma de `data`; agregarlo a `examples/batch.valid.json` |
| Nuevo tipo de lote | Agregarlo a `batch_type`, crear `batches/<tipo>.schema.json` con su ejemplo válido y agregar su rama en `batch.schema.json` |
| Nuevo tipo de condición final | Agregarlo a `end_condition_type` y agregar su rama en `reference.schema.json` |
| Nuevo mensaje | Agregarlo a `message_type` y documentarlo en `extension-messages.md` |

Las pruebas fallan si falta alguna de estas piezas. Todo cambio actualiza la versión de los contratos según las reglas de `extension-messages.md`.
