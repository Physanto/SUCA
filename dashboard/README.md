# Panel de resultados

Muestra lo que pasó en cada sesión y dónde están los problemas del sistema evaluado: sesiones, tareas, pantallas, índice de usabilidad y referencias. Está hecho con Streamlit y lee la base de datos **solo** a través de `data.py`.

## Cómo se abre

Desde la raíz del repositorio, con el entorno virtual activo:

```bash
python -m streamlit run dashboard/app.py
```

Se abre en `http://127.0.0.1:8501`. La configuración de Streamlit está en `.streamlit/config.toml`, que Streamlit lee de la carpeta desde la que se ejecuta. Escucha solo en esta computadora (el panel muestra datos de participantes) y no envía estadísticas de uso.

En la barra lateral se elige:
- **Base de datos:** real (`database.path`) o simulada (`database.mock_path`). Por defecto, la real si existe; si no, la simulada. La simulada se crea con `python -m scripts.generate_mock_data`.
- **Estudio:** uno de los estudios de esa base.

## Archivos

| Archivo | Qué hace |
|---|---|
| `app.py` | Navegación: registra las páginas (`PAGES`) y muestra los selectores de base y estudio |
| `data.py` | `DashboardData`: todas las consultas del panel y su única escritura. No importa Streamlit |
| `ui.py` | Ayudas de Streamlit: selectores, base elegida (`selected_data`), estudio elegido (`selected_study`), encabezado de página y tablas en español (`show_table`) |
| `charts.py` | Gráficas de Altair de todas las páginas (línea de tiempo, señal facial, incidentes, tareas, índice) y el resumen por tarea |
| `heatmap.py` | Mapas de calor de clics, cursor y mirada sobre la captura de cada pantalla |
| `replay.py`, `replay-player.html` | Reproducción visual de una sesión y la comprobación de la mirada con los clics |
| `pages/` | Una página por archivo |

## Páginas

| Archivo | Título | Qué muestra |
|---|---|---|
| `pages/sessions.py` | Sesiones | Lista filtrable por versión y modo; cantidad por versión, SUS e IUC medios |
| `pages/session.py` | Sesión | Resumen (duración, tareas con éxito, incidentes, SUS, IUC, error y distancia de cada calibración); línea de tiempo con tareas, pantallas, episodios, incidentes y clics; señal facial; mapa de calor de clics, cursor o mirada por pantalla; tablas |
| `pages/tasks.py` | Tareas | Tasa de éxito y duración de cada tarea por versión; resumen con duración y pasos medianos y el paso de desvío más frecuente |
| `pages/screens.py` | Pantallas | Incidentes por pantalla (por tipo) y tiempo en cada una; mapa de calor de todas las sesiones del estudio, por versión |
| `pages/index.py` | Índice | IUC medio por versión; componentes por versión; IUC frente a SUS con la correlación de Spearman |
| `pages/references.py` | Referencias | Pasos de cada referencia, con la marca de obligatorio editable; elección de la condición final entre las candidatas; **Confirmar referencia** (la única escritura) |
| `pages/replay.py` | Reproducción | La sesión dibujada sobre cada pantalla (cursor, clics, scroll y mirada), con reproducir, velocidad y la línea de tiempo con tareas e incidentes; y la distancia entre la mirada y cada clic |

### Mapas de calor (`heatmap.py`)

Las posiciones se llevan a coordenadas de la **página** (ventana + scroll de ese momento). El fondo es la última captura de referencia de esa pantalla (`screen_capture`), escalada al ancho de la ventana de la sesión; sin captura, un fondo neutro. La captura muestra lo que se veía en la ventana al tomarla: los puntos más abajo se cuentan como "fuera de la imagen". La pantalla de cada punto se calcula con la misma regla que el análisis (`screen_key`).

### Reproducción (`replay.py`, `replay-player.html`)

**No vuelve a ejecutar la prueba**: lo escrito nunca se captura, la tienda no queda en el mismo estado y volver a pulsar haría las acciones de nuevo. Dibuja lo capturado en el tiempo en que pasó. `build_payload` arma los datos (tiempos en ms desde el inicio, coordenadas de la ventana) con las capturas como imágenes JPEG incrustadas; `player_html` los pone en `replay-player.html`, una página sin recursos externos que la página muestra con `st.iframe`.

**Mirada en cada clic.** Casi siempre se mira lo que se pulsa: para cada clic se toma la mediana de la mirada válida entre 0,5 s antes y 0,1 s después, y se mide la distancia al clic. La página da la mediana (en píxeles y en grados, a la distancia medida en la calibración) y la fracción de clics con la mirada a menos de 100 px. Es una comprobación de que la mirada funciona, no una medida de precisión: la persona puede mirar a otro lado al pulsar.

## Funciones de datos

`open_data(ruta)` abre una base y la cierra al salir del bloque. Las páginas la reciben ya abierta con `ui.selected_data()`. Todas las funciones devuelven DataFrames con los campos JSON ya convertidos a diccionarios y listas, y las marcas de tiempo en ms desde 1970 (`ui.show_table` las muestra como fecha y hora).

| Función | Devuelve |
|---|---|
| `get_studies()` | Estudios con su cantidad de sesiones |
| `get_sessions(study_id, versions, modes)` | Sesiones con duración, incidentes, SUS e IUC; filtros opcionales |
| `get_session(session_id)` | Un diccionario con los datos de la sesión, o `None` |
| `get_events(session_id, types)` | Eventos, con `url`, `title`, `element` y `data` |
| `get_session_tasks(session_id)` | Tareas de una sesión guiada con su resultado (`success`, `steps`, `deviation_step`…) |
| `get_incidents(session_id, study_id)` | Incidentes de una sesión o de un estudio |
| `get_episodes(session_id)` | Episodios con su duración y `metrics` |
| `get_face(session_id)` | Muestras faciales con sus `values` |
| `get_gaze(session_id, valid_only)` | Muestras de mirada (por defecto, solo las válidas) |
| `get_calibrations(session_id)` | Cada intento de calibración: error en px y en grados, si se aceptó y la distancia medida |
| `get_task_results(study_id)` | Resultados por tarea de todas las sesiones del estudio, con versión y participante |
| `get_screen_summary(study_id)` | Por pantalla normalizada: visitas, sesiones, tiempo e incidentes |
| `get_usability_index(study_id)` | Índice y componentes de cada sesión, con su SUS |
| `get_references(study_id, status)` | Referencias de las tareas: pasos, candidatas, condición y pasos obligatorios |
| `get_screen_captures(study_id)` | Capturas de referencia para los mapas de calor, con `absolute_path` |
| `confirm_reference(reference_id, end_condition, required_steps)` | **La única escritura:** confirma la condición final y marca los pasos obligatorios. La valida con el contrato de referencias y rechaza posiciones que no existen en `steps` |

Los id pueden venir directamente de un DataFrame (`numpy.int64`): `data.py` los convierte.

Para agregar una consulta, agrega un método `get_…` a `DashboardData`, con su prueba en `tests/dashboard/test_data.py`.

## Cómo se agrega una página

1. Crea el archivo en `pages/` (nombre en `snake_case`):

   ```python
   """Página Episodios: episodios de todas las sesiones del estudio."""

   from dashboard import ui

   ui.page_header("Episodios", "qué se muestra cuando esté completa.")

   with ui.selected_data() as data:
       sessions = data.get_sessions(study_id=ui.selected_study(data))
       episodes = [data.get_episodes(session_id) for session_id in sessions["session_id"]]

   for table in episodes:
       ui.show_table(table)
   ```

2. Regístrala en `PAGES`, en `app.py`, con su título y su ícono. La navegación no cambia.
3. Agrégala a `TITLES` en `tests/dashboard/test_pages.py`.

Reglas:
- **Las páginas no escriben SQL:** piden los datos a `DashboardData`. Si falta una consulta, se agrega a `data.py`.
- **Textos en español:** títulos, etiquetas y mensajes. `ui.show_table` traduce las columnas con `ui.COLUMN_LABELS`; agrega ahí las columnas nuevas.
- **Caché en las páginas, no en `data.py`.** Si una consulta es lenta, se usa la ruta de la base como clave de la caché:

  ```python
  @st.cache_data(ttl=60)
  def load_events(path: str, session_id: int) -> pd.DataFrame:
      with open_data(path) as data:
          return data.get_events(session_id)


  events = load_events(str(ui.selected_path()), session_id)
  ```

## Pruebas

```bash
pytest tests/dashboard
```

- `test_data.py` prueba cada función de datos sobre la base simulada y compara con su verdad de referencia. También comprueba que leer nunca escribe, que `data.py` no importa Streamlit y que ninguna página tiene SQL.
- `test_pages.py` ejecuta la navegación y cada página sin navegador, con `AppTest` de Streamlit. Con `st.navigation`, `AppTest` no vuelve a ejecutar `app.py` al cambiar de página, así que cada página se prueba ejecutándola directamente.
