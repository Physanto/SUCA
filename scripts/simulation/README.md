# Datos simulados

Sesiones falsas pero realistas, con problemas conocidos y la **verdad de referencia** de cada una: los incidentes, episodios, resultados por tarea e índice que el análisis debería encontrar. Sirven para probar el análisis y el panel de resultados sin datos de participantes.

| Archivo | Qué hace |
|---|---|
| `builder.py` | `SessionBuilder`: arma una sesión paso a paso y anota su verdad de referencia |
| `scenarios.py` | La tienda simulada (pantallas, elementos, rutas de las 4 tareas de `studies/example.yaml`) y las sesiones de la base simulada |
| `store.py` | Guarda las sesiones por el mismo camino que los datos reales y ayuda a las pruebas |
| `../generate_mock_data.py` | Genera la base simulada completa y su verdad de referencia |

## Generar la base simulada

```bash
python -m scripts.generate_mock_data            # database.mock_path (data/mock.db), semilla 7
python -m scripts.generate_mock_data --db data/otra.db --seed 3
```

- Recrea la base desde cero. Nunca escribe sobre `database.path`, la base de las sesiones reales.
- Con la misma semilla, la base y la verdad son **idénticas** en cualquier computadora.
- Escribe la verdad junto a la base: `data/mock_ground_truth.json`.
- Tarda unos segundos: cada registro se valida con los contratos al guardarse.

Contenido:

| Sesión | Modo | Versión | Qué tiene |
|---|---|---|---|
| `reference` | `reference` | V0 | El evaluador graba la ruta correcta de las 4 tareas; quedan 4 referencias confirmadas |
| `guided_v0` | `guided` | V0 | Las 4 tareas por la ruta correcta, sin incidentes |
| `guided_v1` | `guided` | V1 | Problemas 1 a 4 |
| `guided_v2` | `guided` | V2 | Problemas 1 a 8, un desvío conocido (tarea 3: elige transferencia antes que tarjeta) y una tarea abandonada (tarea 4) |
| `free_v1` | `free` | V1 | Búsquedas con errores, imagen que parece botón, botón lento, ida y vuelta entre pantallas, pausa y formulario abandonado |

Las sesiones guiadas tienen calibración inicial y final, SUS, mirada y rostro. La mirada y el rostro van a 10 y 5 Hz (en la extensión, a las frecuencias de la configuración), para que la base sea pequeña.

Las **tablas de resultados** (`episode`, `incident`, `task_result`, `usability_index`) quedan llenas con la verdad de referencia, para que el panel de resultados tenga qué mostrar antes de que existan los detectores. El índice se guarda con la versión `mock`. Ejecutar `python -m analysis.run --db data/mock.db …` reemplaza esos resultados por los del pipeline; para recuperarlos, vuelve a generar la base.

## La verdad de referencia

`mock_ground_truth.json` tiene:

- `seed`, `params_version` (de `parameters.yaml`), `contract_version` y `friction_i_max` (el usado para el índice);
- `conventions`: cómo leer cada dato (también abajo);
- `seeded_problems`: el catálogo de problemas sembrados (`problem` de cada incidente);
- `study`, `references`: id de las tareas y de sus referencias, con duración, pasos y condición final;
- `sessions`: por sesión, su `session_id`, `incidents`, `episodes`, `tasks` (resultados por tarea), `usability_index` y `sus_score`.

Convenciones:

- **Pantalla:** ruta normalizada, sin dominio ni parámetros, con `{id}` en lugar de los identificadores (`/order/{id}/confirmation`).
- **Incidente:** `t_start` y `t_end` delimitan el patrón (por ejemplo, del primer al último clic de la ráfaga). Un detector acierta si informa un incidente del mismo tipo, en la misma sesión, con `t` dentro de ese intervalo.
- **Pasos:** clics en elementos interactivos, envíos de formulario y cambios de pantalla.
- **Desvío:** un paso está en la ruta si es el siguiente esperado de la referencia o repite uno ya hecho (otro clic en el mismo botón, reenviar el formulario). El primer paso que no cumple esto es el desvío; `deviation_step` es la posición (desde 0) del paso esperado en ese momento, y `off_path_ms` suma el tiempo fuera de la ruta.
- **Éxito:** la tarea llegó al final de su ruta, con sus pasos obligatorios.
- **Índice:** las fórmulas del índice, con la duración y los pasos de las referencias; la fricción usa `friction_i_max` (incidentes por minuto de tarea).

## Usar el constructor en las pruebas

Una sesión es una línea de tiempo: cada método agrega algo al final y devuelve el mismo constructor.

```python
from scripts.simulation import store
from scripts.simulation.builder import Click, SessionBuilder
from scripts.simulation.scenarios import ADD_TO_CART, CART, CART_LINK, HOME, ZOOM_BADGE


def test_finds_a_dead_click(tmp_path, params):
    connection = store.create_database(tmp_path / "test.db")   # esquema + estudio de ejemplo
    session = (
        SessionBuilder(study_id=1, mode="free", seed=1)
        .on_screen(HOME)
        .with_dead_click(ZOOM_BADGE)
        .do(Click(CART_LINK, to=CART))
        .build()
    )
    data = store.load_session(connection, session)            # SessionData, como lo recibe una etapa

    found = DeadClickDetector().find(data, params)

    assert list(found["t"]) == [item.t_start for item in session.truth.incidents]
```

- **Patrones:** `with_rage_click`, `with_dead_click`, `with_navigation_loop`, `with_form_error`, `with_repeated_search`, `with_long_pause`, `with_hesitation`, `with_form_abandonment`, `with_overtime` y `with_deviation_at_step`.
- **Tareas:** `with_task(task_id, ruta)` empieza una tarea; `follow(n)` hace las siguientes acciones de la ruta; `end_task("reference" | "done" | "gave_up")` la termina. `do(...)` hace acciones fuera de la ruta y `redo(...)` repite acciones de la ruta sin que cuenten como desvío.
- **Umbrales:** los patrones leen `analysis/parameters.yaml` y por defecto lo superan. Con valores por debajo del umbral (`with_rage_click(clicks=2)`, `with_long_pause(ms=1000)`), el patrón ocurre pero la verdad no lo cuenta: sirve para el caso negativo de cada detector. El comportamiento normal nunca cruza ningún umbral. Para probar con otros umbrales, pasa `params=` al constructor.
- **Verdad:** `session.truth.incidents`, `.episodes`, `.tasks` y `.usability_index`.
- **Sin base:** `session.batches` tiene los registros por tipo de lote, con la forma de los contratos.
- **Misma semilla, misma sesión.**
- **Sesiones completas:** `scenarios.guided_v1(context)` y las demás funciones de escenario devuelven las sesiones de la base simulada con su verdad. `context` es un `scenarios.StudyContext`; ver `tests/simulation/conftest.py`.

## Pruebas

```bash
pytest tests/simulation
```

Comprueban:
- **Determinismo:** dos generaciones dan bases idénticas.
- **Contratos:** cada registro cumple el suyo.
- **Coherencia:**
  - la verdad coincide con los eventos guardados: ráfagas dentro de los umbrales, y los clics sin respuesta y las pausas largas de los eventos son exactamente los de la verdad;
  - la verdad coincide con las tablas de resultados y con las fórmulas del índice.
- **Pipeline:** corre sobre la base simulada.
