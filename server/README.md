# Servidor local

Recibe los datos de la extensión, los valida contra los contratos de `contracts/` y los guarda en la base SQLite. **No analiza**: eso lo hace `analysis/` después de cada sesión.

## Ejecutar

Con la base creada (`python -m scripts.init_db`) y un estudio cargado:

```bash
python -m server
```

Escucha en `server.host` y `server.port` de `config/shared.json`, por defecto `http://127.0.0.1:8765`. La configuración solo admite direcciones de loopback, así que el servidor nunca queda accesible desde otras computadoras. Si la base no existe o tiene otra versión del esquema, el servidor no arranca y explica cómo resolverlo.

Para comprobar que responde:

```bash
curl -H "X-Api-Token: suca-local-dev-token" http://127.0.0.1:8765/health
```

## Endpoints

**Todas** las peticiones llevan el encabezado `X-Api-Token` con `server.token` de la configuración; sin él, la respuesta es 401. Los cuerpos son JSON y cumplen los esquemas de `contracts/requests/` o, en los lotes, `contracts/batch.schema.json`. Los ejemplos de `contracts/examples/` sirven como modelo.

| Método y ruta | Cuerpo | Respuesta | Errores |
|---|---|---|---|
| `GET /health` | — | `{"status": "ok", "contract_version": "1.8.0", "schema_version": "8"}` | 401 |
| `GET /studies` | — | `[{"id", "name", "system_under_test", "description", "recorded_fields"}]` | 401 |
| `GET /studies/{id}/tasks` | — | Tareas en orden: `[{"id", "position", "instruction", "references": [{"id", "end_condition"}]}]`, solo con referencias confirmadas | 401, 404 |
| `POST /sessions` | `new-session` | 201 `{"session_id", "started_at"}` | 401, 422 |
| `POST /sessions/{id}/batches` | Lote | `{"stored": <registros>}` | 401, 404, 409, 422 |
| `POST /sessions/{id}/sus` | `sus-answers` | `{"score"}`, de 0 a 100 | 401, 404, 409, 422 |
| `POST /sessions/{id}/close` | — | `{"session_id", "ended_at"}` | 401, 404 |
| `POST /references` | `new-reference` | 201 `{"reference_id"}` | 401, 422 |
| `POST /captures` | `new-capture` | 201 `{"capture_id", "file_path"}` | 401, 422 |
| `POST /sessions/{id}/frames` | `new-frame` | 201 `{"frame_id", "file_path"}`; la imagen queda en `data/frames/<sesión>/` | 401, 404, 409, 422 |

Detalles de cada uno:

- **Sesiones:** `started_at` y `ended_at` los pone el servidor, en milisegundos desde 1970 (el mismo reloj que la extensión). Si el código de participante es nuevo, se crea el participante. Cerrar una sesión ya cerrada no la cambia y devuelve el mismo `ended_at`.
- **Lotes:** se guardan completos o no se guardan. Además del contrato, el servidor comprueba que cada `task_id` sea del estudio de la sesión. Un lote para una sesión cerrada se rechaza con 409, así que la extensión debe enviar los lotes pendientes **antes** de cerrar la sesión.
- **SUS:** el puntaje se calcula con la fórmula estándar. Volver a enviar las respuestas las reemplaza.
- **Reintentos:** reenviar un registro de `tasks`, el SUS o un cierre no da error. Reenviar un lote de eventos o de muestras los duplica; el análisis quita los duplicados.
- **Referencias:** el panel lateral guarda así la grabación de una tarea hecha en una sesión de modo `reference`. La referencia nace en estado `draft` y sin pasos; el análisis agrega los pasos y las condiciones candidatas, y el evaluador confirma la condición final en el panel de resultados. Guardar dos veces la misma tarea de la misma sesión devuelve la misma referencia.
- **Capturas:** la imagen llega como *data URL* PNG o JPEG, tal como la entrega `chrome.tabs.captureVisibleTab`, y se guarda en `captures/<study_id>/<nombre generado>` junto a la base de datos (por defecto `data/captures/`). El nombre lo genera el servidor; el tamaño máximo es 10 MB.
- **Capturas de la sesión:** solo JPEG, de una sesión abierta, en `frames/<session_id>/`. Borrar la sesión borra sus filas; si un participante se retira, borra también esa carpeta.

### Errores

Todos los errores tienen la forma `{"detail": "<resumen>"}`.

| Código | Cuándo |
|---|---|
| 401 | Falta `X-Api-Token` o no coincide |
| 404 | No existe el recurso de la ruta (`/sessions/{id}`, `/studies/{id}`) |
| 409 | La sesión de la ruta está cerrada |
| 422 | El cuerpo no cumple su contrato, nombra algo que no existe (por ejemplo `study_id`), el lote es de otra versión mayor de los contratos o trae el texto de un campo que el estudio no declaró en `recorded_fields` |
| 500 | Error interno; no se guardó nada del lote |

Los 422 agregan `errors`, una lista con el registro (posición en el lote, o `null`), el campo y el motivo:

```json
{
  "detail": "batch does not match its contract",
  "errors": [
    { "record": 3, "field": "x", "message": "'x' is a required property" },
    { "record": 10, "field": "element/text", "message": "'…' is too long" }
  ]
}
```

Un 4xx no se resuelve reintentando la misma petición; un fallo de red o un 5xx, sí.

### Sin CORS

El servidor no habilita CORS a propósito. El service worker y el panel lateral son páginas de la extensión, y Chrome no les aplica CORS hacia los hosts de su `host_permissions`. Una página web cualquiera, en cambio, no puede enviar el encabezado `X-Api-Token`, porque el navegador antes hace una consulta previa que el servidor no autoriza. Los content scripts sí están sujetos a CORS: por eso envían todo a través del service worker.

## Estructura

| Archivo | Responsabilidad |
|---|---|
| `__main__.py` | Arranque con uvicorn en la dirección de la configuración |
| `app.py` | `create_app(config)`: comprueba la base, define cómo se abre el repositorio de cada petición, registra los endpoints con el token y traduce los errores a HTTP |
| `security.py` | Comprobación del token |
| `routes.py` | Endpoints: solo traducen HTTP y llaman a `services` |
| `services.py` | Casos de uso: validan contra los contratos, aplican las reglas y usan los repositorios. No saben de HTTP |
| `repositories.py` | Interfaces pequeñas (`Protocol`) por necesidad y su implementación SQLite. Único archivo con SQL y único que escribe archivos |
| `ingestion.py` | Un manejador por tipo de lote, registrado por su tipo |
| `schema.sql` | Esquema de la base |

Cada petición usa su propia conexión a SQLite, que se cierra al terminar.

## Pruebas

```bash
pytest tests/server
```

Las pruebas crean una base temporal con el estudio de ejemplo, fijan el reloj del servidor y cubren cada endpoint y cada error. Cada ejemplo válido de `contracts/examples/` que es un lote o un cuerpo de petición se envía y se comprueba que quedó guardado.

## Cómo extender

- **Nuevo tipo de lote:** agrega el tipo y su esquema en `contracts/` (ver su README), su tabla en `schema.sql` y un manejador en `ingestion.py`:

  ```python
  @register("new_type")
  def store_new_type(
      writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]
  ) -> None:
      """Guarda registros de new_type en new_table."""
      writer.insert("new_table", [{"session_id": session_id, "t": record["t"]} for record in records])
  ```

  El endpoint de lotes y `services.store_batch` no cambian. Una prueba falla si un tipo de lote no tiene manejador.
- **Nuevo endpoint:** el formato del cuerpo va en `contracts/requests/`, la lógica en una función de `services.py` que reciba solo las interfaces que use, el SQL en `repositories.py` y la ruta en `routes.py`.
- **Sustituir dependencias en pruebas:** `app.dependency_overrides[routes.get_repository]` o `[routes.get_clock]`.

### Actualizar una base del esquema 7

Detén el servidor y cualquier análisis que escriba, y ejecuta:

```bash
python -m scripts.migrate_db --db data/otra.db
```

Crea un respaldo SQLite consistente antes de cambiar nada, agrega las tablas de
atribución del esquema canónico y `calibration.css_px_per_cm`, y actualiza la
versión a 8 en una transacción. Si falla, revierte la migración y conserva el
respaldo. Una base ya actualizada no cambia. No migra versiones anteriores a 7;
la base simulada antigua se regenera con `scripts.generate_mock_data`.
Los reintentos de una calibración idéntica se guardan una sola vez; una nueva
medición con otro momento se conserva aunque tenga el mismo error.
