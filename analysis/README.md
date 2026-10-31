# Análisis

Procesa las sesiones terminadas: limpia los datos, identifica las pantallas, segmenta la sesión en episodios, detecta incidentes de fricción, compara cada tarea con sus referencias y calcula el índice de usabilidad conductual (`bui`). Corre **después** de cada sesión, no en tiempo real, así que se puede recalcular todo cuando cambian los parámetros.

## Cómo se ejecuta

Desde la raíz del repositorio, con el entorno virtual activo:

```bash
python -m analysis.run --session 17                  # una sesión
python -m analysis.run --study 2                     # las sesiones cerradas de un estudio
python -m analysis.run --session 17 --db data/mock.db   # otra base (por defecto, database.path)
```

- Cada sesión analizada imprime un resumen, por ejemplo `session 17: 2 episodes, 5 incidents, 4 task results, bui 71.3 (12.4 ms)`. El tiempo de cada etapa se registra en la salida de errores.
- Volver a analizar una sesión **reemplaza** sus resultados; nunca los duplica.
- `--study` salta las sesiones abiertas y las nombra. Si una sesión falla, informa el error y sigue con las demás.
- `--session` analiza también una sesión abierta (por ejemplo, si se cerró el panel sin cerrarla), con un aviso.
- Código de salida: 0 si todo se analizó; 1 si algo falló (sesión o estudio inexistente, base inexistente, una etapa con error).

## El pipeline

`run.py` ejecuta siete etapas con nombre. Cada una es una función con firma fija:

| # | Etapa | Función | Devuelve |
|---|---|---|---|
| 1 | `cleaning` | `cleaning.clean(data, params)` | `SessionData` limpio |
| 2 | `screens` | `screens.assign_screens(data, params)` | `SessionData` con `events.screen` normalizado |
| 3 | `episodes` | `episodes.detect(data, params)` | DataFrame de la tabla `episode` |
| 4 | `detectors` | `detectors.detect(data, params)` | DataFrame de la tabla `incident` |
| 5 | `reference_drafts` | `reference.extract_drafts(data, params)` | Pasos y candidatas de las grabaciones, para guardar en `reference` como borradores |
| 6 | `reference` | `reference.compare(data, params)` | DataFrame de la tabla `task_result` |
| 7 | `usability_index` | `usability_index.compute(data, task_results, incidents, params)` | DataFrame de la tabla `usability_index` (una fila o ninguna) |

```
loader.load_session ─► cleaning ─► screens ─► episodes ─► detectors ─► reference_drafts ─► reference ─► usability_index ─► loader.save_results
```

- A la salida de cada etapa se validan sus columnas. Si una etapa falla o devuelve columnas incorrectas, el análisis de esa sesión se detiene con un mensaje como `stage 'detectors' failed: detector rage_click: missing columns ['t']`, y no se guarda nada: los resultados anteriores quedan como estaban.
- Al final, `loader.save_results` borra los resultados previos de la sesión y guarda los nuevos en una sola transacción, con la versión de los parámetros.

## Archivos

| Archivo | Qué hace |
|---|---|
| `run.py` | Pipeline y línea de comandos |
| `loader.py` | Repositorio: `SessionData`, carga de sesiones y guardado de resultados. Es el único archivo del análisis con SQL |
| `columns.py` | Columnas y tipos de cada tabla; `frame`, `empty`, `validate`, `concat` |
| `registry.py` | Registro genérico de estrategias |
| `parameters.py`, `parameters.yaml` | Umbrales y valores del índice, validados al cargar |
| `cleaning.py`, `screens.py` | Etapas 1 y 2 |
| `episodes.py`, `detectors.py` | Etapas 3 y 4: fachadas que ejecutan los detectores registrados |
| `reference.py`, `usability_index.py` | Etapas 5 a 7 |
| `ml/` | Modelo de aprendizaje automático (fase posterior) |

Reanalizar actualiza los borradores de referencia y conserva los que el evaluador ya confirmó.

## Datos que recibe cada etapa

`SessionData` (en `loader.py`) es inmutable y tiene:

| Campo | Contenido |
|---|---|
| `session` | `SessionInfo`: `id`, `study_id`, `participant_id`, `version`, `mode`, `started_at`, `ended_at`, `screen_info`, `closed` |
| `events` | Eventos ordenados por tiempo: `t`, `type`, `x`, `y`, `url`, `title`, `screen`, `task_id`, `element`, `data` |
| `gaze` | Mirada: `t`, `x`, `y`, `scroll_x`, `scroll_y`, `element_selector`, `zone`, `valid` |
| `face` | Rostro: `t`, `values` (diccionario), `head_yaw`, `head_pitch`, `face_detected` |
| `calibrations` | `t`, `type`, `error_px`, `error_deg`, `accepted`, `camera_delay_ms` |
| `tasks` | Tareas del modo guiado: `task_id`, `t_start`, `t_end`, `ended_by` |
| `references` | Referencias **confirmadas** del estudio: `id`, `task_id`, `steps`, `end_condition`, `required_steps`, `duration_ms` |

- Los tiempos están en milisegundos desde 1970, con el mismo reloj en todas las tablas.
- `element`, `data`, `values`, `steps`, `end_condition` y `required_steps` ya son diccionarios o listas.
- `screen` es la URL al cargar. La etapa `screens` la reemplaza por la pantalla normalizada (`/order/8812` → `/order/{id}`); `url` y `title` quedan como se capturaron. Las etapas siguientes agrupan por `screen`.
- Los mismos datos pueden traer registros duplicados (un lote reenviado llega dos veces): la etapa `cleaning` los quita.

**Reglas de las etapas:**
- Una etapa **nunca modifica** `data` ni sus DataFrames. Si cambia algo, devuelve una copia: `dataclasses.replace(data, events=nuevos_eventos)`.
- Puede agregar columnas a los DataFrames de `SessionData`, pero no quitar las de la tabla de arriba.
- Los umbrales salen de `params` y los tipos de evento, incidente y episodio, del contrato: nunca se escriben números ni valores de enumeraciones a mano.

## Tablas de resultados

Las columnas exactas y sus tipos están en `columns.py`. Los DataFrames de resultados **no** llevan `session_id` (ni `params_version` en el índice): los agrega el repositorio al guardar.

| Tabla | Columnas |
|---|---|
| `episode` | `type` (`episode_type`), `t_start`, `t_end`, `screen`, `outcome`, `metrics` (diccionario) |
| `incident` | `type` (`incident_type`), `t`, `screen`, `task_id`, `element` (diccionario) |
| `task_result` | `task_id`, `success`, `duration_ms`, `steps`, `deviation_step`, `off_path_ms` (una fila por tarea) |
| `usability_index` | `effectiveness`, `time_efficiency`, `path_efficiency`, `friction`, `bui` (una fila o ninguna) |

Para armar un resultado con los tipos correctos, usa `columns.frame(tabla, filas)` con una lista de diccionarios, o `columns.empty(tabla)` si no hay filas. Las columnas que admiten vacío se pueden omitir. `columns.validate(df, tabla)` explica todo lo que está mal en un solo error.

## Parámetros

Los umbrales y los valores del índice están en `parameters.yaml`, con un comentario cada uno. `load_parameters()` los valida al cargar: una clave faltante o desconocida, o un valor fuera de rango, es un error que nombra la clave. Las etapas los leen como atributos: `params.rage_click.window_ms`, `params.friction_i_max`…

`version` se guarda con cada índice calculado. **Si cambias un umbral, cambia también la versión.**

El análisis extrae pasos y propone condiciones finales a partir de URL, textos y roles registrados. En sesiones guiadas alinea rutas alternativas y exige los pasos obligatorios de una misma referencia para decidir el éxito. Repetir pasos no es desvío; `deviation_step` indica la posición esperada desde 0 y `off_path_ms` suma el tiempo hasta retomar la ruta o terminar.

| Componente (0–100; mayor es mejor) | Cálculo |
|---|---|
| `effectiveness` | `100 * completadas / tareas_de_la_sesion` |
| `time_efficiency` | `100 * promedio(min(1, t_ref / t_usuario))`, solo completadas |
| `path_efficiency` | `100 * promedio(min(1, pasos_ref / pasos_usuario))`, solo completadas |
| `friction` | `100 * (1 - min(1, i / friction_i_max))`; `i` son incidentes asociados por minuto de tarea |
| `bui` | Promedio de los cuatro componentes |

Sin tareas completadas, las eficiencias valen 0. No hay índice en modo libre ni de referencia, con datos incompletos o duración total nula. `friction_i_max` sigue en `null` hasta el piloto: la ejecución normal no guarda índices. Las pruebas simuladas configuran 15 y guardan la versión `mock`.

## Cómo agregar un detector

1. Elige su tipo en la enumeración `incident_type` del contrato (`contracts/enums.json`). Si el tipo no existe, se pide agregarlo al contrato: el registro rechaza los tipos que no están ahí.
2. En `detectors.py`, escribe una clase con el atributo `incident_type` y el método `find`, y regístrala:

   ```python
   @DETECTORS.register
   class DeadClickDetector:
       """Clic sin cambios en la página ni navegación en el tiempo de espera."""

       incident_type = "dead_click"

       def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
           """Busca los clics sin respuesta."""
           rows = []
           for click in data.events[data.events["type"] == "click"].itertuples():
               if ...:  # sin click_response en params.dead_click.wait_ms
                   rows.append(
                       {
                           "type": self.incident_type,
                           "t": click.t,
                           "screen": click.screen,
                           "task_id": click.task_id,
                           "element": click.element,
                       }
                   )
           return columns.frame("incident", rows)
   ```

3. `find` devuelve las columnas de `incident`, todas las filas con `type` igual a su `incident_type`. Si no encuentra nada, devuelve `columns.empty("incident")`.
4. Agrega sus pruebas en `tests/analysis/`, con un caso que debe detectar y uno que no.

`detectors.detect` lo ejecuta junto con los demás, valida su resultado y une todos los incidentes por tiempo. Ni `detect` ni `run.py` cambian. Si el detector falla o devuelve columnas incorrectas, el error lo nombra.

Los **detectores de episodios** se agregan igual en `episodes.py`: atributo `episode_type`, registro con `@EPISODE_DETECTORS.register` y columnas de la tabla `episode`.

## Pruebas

```bash
pytest tests/analysis
python -m pytest tests/analysis/test_m5_mock_verification.py tests/integration/test_m5_recorded_reference.py -q
```

- `conftest.py` crea una base pequeña: una sesión guiada cerrada con datos de todos los tipos, una sesión libre abierta, y referencias confirmadas y en borrador.
- `test_m5_mock_verification.py` contrasta éxito, desvío e índice con la verdad simulada y verifica la persistencia, usando los incidentes que produce el pipeline. `test_usability_index.py` incluye el cálculo manual del BUI.
- `test_m5_recorded_reference.py` reproduce dos clics reales de `extension/test-page/` por la API y comprueba la candidata `/extension/test-page/second-page.html`, su confirmación y su conservación al reanalizar. La fixture está en `tests/integration/fixtures/reference_test_page.json`. La grabación usa la captura provisional y un arnés de estado y transporte; no cubre el panel lateral, el worker, la cámara ni la aplicación de prueba. Su reproducción no necesita navegador.
- Para probar un detector sin dejarlo registrado en las demás pruebas, crea un `Registry` propio, registra la clase y reemplaza el de la etapa con `monkeypatch.setattr(detectors, "DETECTORS", registro)` (ver `test_stages.py`).
- Para probar `find` directamente, basta con instanciar la clase y pasarle un `SessionData` cargado de la base de prueba.
- Para armar casos con patrones conocidos (una ráfaga de clics, una pausa por debajo del umbral, un desvío en un paso dado), usa el constructor de sesiones simuladas: `SessionBuilder` de `scripts/simulation/builder.py` y `store.load_session` para obtener el `SessionData`. Cada sesión trae su verdad de referencia (`session.truth`). Ver `scripts/simulation/README.md`.

## Datos simulados

`python -m scripts.generate_mock_data` crea `data/mock.db` con sesiones de problemas conocidos y `data/mock_ground_truth.json` con los resultados esperados. Para comparar el análisis con la verdad de referencia:

```bash
python -m analysis.run --study 1 --db data/mock.db
```

Esto reemplaza los resultados esperados que trae la base por los del pipeline. Para recuperarlos, vuelve a generarla.
