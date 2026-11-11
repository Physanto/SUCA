-- Esquema de la base de datos SQLite del sistema.
--
-- Convenciones:
-- * Marcas de tiempo (t, t_start, t_end, started_at, ended_at): REAL, en
--   milisegundos desde 1970, con el mismo reloj que la extensión.
-- * Campos JSON: TEXT con el documento serializado. Los detalles de cada tipo
--   varían; las columnas que se consultan siempre (t, type, task_id) son propias.
-- * Booleanos: INTEGER 0/1.
-- * Sin restricciones CHECK sobre valores de enumeraciones: los valores se
--   validan con los contratos (contracts/) antes de guardarse.
-- * Borrar una sesión borra en cascada todos sus datos y resultados; borrar un
--   participante borra sus sesiones. Así se atiende una solicitud de retiro.
-- * La versión del esquema está en meta.schema_version. Si cambia el esquema,
--   sube la versión: una base con otra versión se rechaza al abrirla.


-- =====================================================================
-- Estudios, tareas y participantes
-- =====================================================================

-- Estudio: un sistema evaluado con un conjunto de tareas. Se carga desde
-- studies/*.yaml; el nombre lo identifica al volver a cargar el archivo.
CREATE TABLE study (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL UNIQUE,
    system_under_test TEXT    NOT NULL,
    description       TEXT,
    -- JSON: campos cuyo texto se registra ([{name, selector}]); '[]' si ninguno.
    recorded_fields   TEXT    NOT NULL DEFAULT '[]'
);

-- Tarea del modo guiado. La posición (desde 1) la identifica dentro del
-- estudio; recargar el YAML conserva el id de cada posición.
CREATE TABLE task (
    id          INTEGER PRIMARY KEY,
    study_id    INTEGER NOT NULL REFERENCES study (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    instruction TEXT    NOT NULL,
    UNIQUE (study_id, position)
);

-- Participante, identificado solo por un código anónimo.
CREATE TABLE participant (
    id                 TEXT    PRIMARY KEY,  -- código anónimo, nunca un nombre
    age                INTEGER,
    digital_experience TEXT,
    wears_glasses      INTEGER               -- 0/1; NULL si no se registró
);


-- =====================================================================
-- Captura
-- =====================================================================

-- Sesión de un participante (o del evaluador, en modo reference).
CREATE TABLE session (
    id                      INTEGER PRIMARY KEY,
    study_id                INTEGER NOT NULL REFERENCES study (id),
    participant_id          TEXT    NOT NULL REFERENCES participant (id) ON DELETE CASCADE,
    version                 TEXT    NOT NULL,  -- versión del sistema evaluado (V0, V1…)
    mode                    TEXT    NOT NULL,  -- session_mode
    started_at              REAL    NOT NULL,
    ended_at                REAL,              -- NULL mientras la sesión está abierta
    screen_info             TEXT,              -- JSON: ventana, pantalla, devicePixelRatio, Chrome
    calibration_error_start REAL,              -- error de la calibración inicial, en grados
    calibration_error_end   REAL               -- error de la validación final, en grados
);

CREATE INDEX session_study_idx ON session (study_id);
CREATE INDEX session_participant_idx ON session (participant_id);

-- Evento de interacción (lote events). Tabla de alto volumen.
CREATE TABLE event (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t          REAL    NOT NULL,
    type       TEXT    NOT NULL,  -- event_type
    x          REAL,
    y          REAL,
    screen     TEXT    NOT NULL,  -- JSON: { url, title }
    task_id    INTEGER REFERENCES task (id),
    element    TEXT,              -- JSON: descriptor del elemento
    data       TEXT               -- JSON: datos propios del tipo de evento
);

CREATE INDEX event_session_t_idx ON event (session_id, t);

-- Muestra de mirada (lote gaze). Tabla de alto volumen (~30 por segundo).
CREATE TABLE gaze_sample (
    session_id       INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t                REAL    NOT NULL,
    x                REAL,             -- NULL si la muestra no es válida
    y                REAL,
    scroll_x         REAL,
    scroll_y         REAL,
    element_selector TEXT,
    zone             TEXT,             -- gaze_zone
    valid            INTEGER NOT NULL, -- 0/1
    state            TEXT,             -- gaze_state; NULL en lotes de contratos anteriores
    confidence       REAL              -- entre 0 y 1; NULL en lotes de contratos anteriores
);

CREATE INDEX gaze_sample_session_t_idx ON gaze_sample (session_id, t);

-- Muestra facial (lote face). Tabla de alto volumen (~15 por segundo).
-- "values" es palabra reservada de SQL: hay que escribirla entre comillas
-- dobles en las consultas.
CREATE TABLE face_sample (
    session_id    INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t             REAL    NOT NULL,
    "values"      TEXT,             -- JSON: face_value → intensidad entre 0 y 1
    head_yaw      REAL,             -- grados
    head_pitch    REAL,             -- grados
    face_detected INTEGER NOT NULL  -- 0/1
);

CREATE INDEX face_sample_session_t_idx ON face_sample (session_id, t);

-- Resultado de una calibración de mirada (lote calibration).
CREATE TABLE calibration (
    session_id      INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t               REAL    NOT NULL,
    type            TEXT    NOT NULL,  -- calibration_type
    error_px        REAL    NOT NULL,
    error_deg       REAL    NOT NULL,
    accepted        INTEGER NOT NULL,  -- 0/1
    viewing_distance_cm REAL,          -- distancia medida en la validación; NULL si no se midió
    camera_delay_ms REAL,
    precision_deg   REAL,              -- temblor de la mirada en la validación; NULL si no se midió
    return_error_deg REAL,             -- error al volver de mirar el teclado; NULL si no se midió
    estimator       TEXT,              -- gaze_estimator; NULL si no se informó
    corrected       INTEGER,           -- 0/1 en drift_check; NULL en los demás tipos
    correction_x_px REAL,              -- corrección de deriva acumulada; NULL si no se informó
    correction_y_px REAL
);

CREATE INDEX calibration_session_t_idx ON calibration (session_id, t);

-- Características de mirada de cada cuadro (lote gaze_features): pose de la
-- cabeza, iris y párpados, estado y punto antes del filtro. Permiten medir y
-- volver a estimar la mirada después de la sesión. Tabla de alto volumen
-- (~30 por segundo, también durante la calibración).
CREATE TABLE gaze_feature (
    session_id      INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t               REAL    NOT NULL,
    face_detected   INTEGER NOT NULL,  -- 0/1
    head_yaw        REAL,              -- grados
    head_pitch      REAL,
    head_roll       REAL,
    head_tx         REAL,              -- centímetros, como los da MediaPipe
    head_ty         REAL,
    head_tz         REAL,
    distance_cm     REAL,              -- con camera.distance_scale
    eye_u           REAL,              -- punto medio entre los ojos en la imagen, 0 a 1
    eye_v           REAL,
    aspect          REAL,              -- ancho / alto del cuadro
    left_h          REAL,              -- iris desde el centro del ojo, en anchos de ojo
    left_v          REAL,
    left_open       REAL,
    left_refined    INTEGER,           -- 0/1
    right_h         REAL,
    right_v         REAL,
    right_open      REAL,
    right_refined   INTEGER,
    blink           REAL,
    state           TEXT    NOT NULL,  -- gaze_state
    confidence      REAL    NOT NULL,
    raw_x           REAL,              -- punto antes del filtro, en la ventana
    raw_y           REAL,
    viewport_width  REAL    NOT NULL,
    viewport_height REAL    NOT NULL,
    scroll_x        REAL    NOT NULL,
    scroll_y        REAL    NOT NULL
);

CREATE INDEX gaze_feature_session_t_idx ON gaze_feature (session_id, t);

-- Punto que se pidió mirar en una calibración, validación o comprobación de
-- deriva (lote gaze_target), con el tramo en que se toman sus muestras.
CREATE TABLE gaze_target (
    session_id       INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t                REAL    NOT NULL,  -- inicio del tramo (t_start del registro)
    t_end            REAL    NOT NULL,
    calibration_type TEXT    NOT NULL,  -- calibration_type
    phase            TEXT    NOT NULL,  -- gaze_target_phase
    "group"          INTEGER NOT NULL,  -- palabra reservada: va entre comillas
    viewport_width   REAL    NOT NULL,
    viewport_height  REAL    NOT NULL,
    points           TEXT    NOT NULL   -- JSON: [{ t, x, y }]
);

CREATE INDEX gaze_target_session_t_idx ON gaze_target (session_id, t);

-- Disposición de la pantalla (lote layout): regiones semánticas y elementos
-- interactivos visibles, con sus rectángulos en la ventana. Se registra con
-- cada captura de la pestaña y permite asignar zona y elemento a un punto de
-- mirada después de la sesión. Nunca lleva texto de la página.
CREATE TABLE page_layout (
    session_id      INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t               REAL    NOT NULL,
    screen          TEXT    NOT NULL,  -- JSON: { url, title }
    viewport_width  REAL    NOT NULL,  -- píxeles CSS
    viewport_height REAL    NOT NULL,
    scroll_x        REAL    NOT NULL,  -- scroll al medir: pasa los rectángulos no fijos a la página
    scroll_y        REAL    NOT NULL,
    regions         TEXT    NOT NULL,  -- JSON: [{ zone, box, fixed }]
    elements        TEXT    NOT NULL,  -- JSON: [{ selector, tag, role, box, fixed }]
    truncated       INTEGER NOT NULL   -- 0/1: se omitieron elementos por el máximo
);

CREATE INDEX page_layout_session_t_idx ON page_layout (session_id, t);

-- Inicio y fin de cada tarea de una sesión guiada (lote tasks).
CREATE TABLE session_task (
    session_id INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    task_id    INTEGER NOT NULL REFERENCES task (id),
    t_start    REAL    NOT NULL,
    t_end      REAL    NOT NULL,
    ended_by   TEXT    NOT NULL,  -- ended_by
    PRIMARY KEY (session_id, task_id)
);

-- Respuestas del cuestionario SUS, una por sesión.
CREATE TABLE sus_response (
    session_id INTEGER PRIMARY KEY REFERENCES session (id) ON DELETE CASCADE,
    answers    TEXT NOT NULL,  -- JSON: las 10 respuestas, de 1 a 5
    score      REAL NOT NULL   -- puntaje SUS, de 0 a 100
);


-- =====================================================================
-- Resultados del análisis
-- Los llena el análisis; se borran y se recalculan por sesión.
-- =====================================================================

-- Episodio reconocido en la sesión (login, formulario, búsqueda, pantalla).
CREATE TABLE episode (
    session_id INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    type       TEXT    NOT NULL,  -- episode_type
    t_start    REAL    NOT NULL,
    t_end      REAL    NOT NULL,
    screen     TEXT,              -- pantalla normalizada (por ejemplo, /order/{id})
    outcome    TEXT,
    metrics    TEXT               -- JSON: métricas propias del tipo de episodio
);

CREATE INDEX episode_session_t_idx ON episode (session_id, t_start);

-- Incidente de fricción detectado.
CREATE TABLE incident (
    session_id INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    type       TEXT    NOT NULL,  -- incident_type
    t          REAL    NOT NULL,
    screen     TEXT,              -- pantalla normalizada
    task_id    INTEGER REFERENCES task (id),
    element    TEXT               -- JSON: descriptor del elemento
);

CREATE INDEX incident_session_t_idx ON incident (session_id, t);

-- Resultado de cada tarea de una sesión guiada.
CREATE TABLE task_result (
    session_id     INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    task_id        INTEGER NOT NULL REFERENCES task (id),
    success        INTEGER NOT NULL,  -- 0/1
    duration_ms    REAL    NOT NULL,
    steps          INTEGER NOT NULL,
    deviation_step INTEGER,           -- primer paso fuera de ruta; NULL si no se desvió
    off_path_ms    REAL,              -- tiempo fuera de ruta; NULL sin referencia
    PRIMARY KEY (session_id, task_id)
);

-- Índice de usabilidad conductual de una sesión y sus componentes (0 a 100).
CREATE TABLE usability_index (
    session_id      INTEGER PRIMARY KEY REFERENCES session (id) ON DELETE CASCADE,
    effectiveness   REAL NOT NULL,
    time_efficiency REAL NOT NULL,
    path_efficiency REAL NOT NULL,
    friction        REAL NOT NULL,
    bui             REAL NOT NULL,
    params_version  TEXT NOT NULL  -- versión de parameters.yaml usada en el cálculo
);


-- Mirada reprocesada al cerrar la sesión (analysis/gaze/refine.py): una fila
-- por cuadro de gaze_feature, con el modelo reajustado, la deriva corregida,
-- el suavizado, la fijación y la zona y el elemento según page_layout.
CREATE TABLE gaze_refined (
    session_id       INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t                REAL    NOT NULL,
    x                REAL,              -- NULL si no mira la pantalla
    y                REAL,
    scroll_x         REAL    NOT NULL,
    scroll_y         REAL    NOT NULL,
    state            TEXT    NOT NULL,  -- gaze_state que dio el monitor en vivo
    confidence       REAL    NOT NULL,
    valid            INTEGER NOT NULL,  -- 0/1: mira la pantalla, dentro de la ventana
    zone             TEXT,              -- gaze_zone
    element_selector TEXT,              -- elemento interactivo bajo el punto, o NULL
    fixation         INTEGER            -- número de fijación (I-DT), o NULL
);

CREATE INDEX gaze_refined_session_t_idx ON gaze_refined (session_id, t);

-- Calidad de la mirada de una sesión: error en vivo y refinado en los puntos de
-- control, medido sin usar cada punto para corregirse a sí mismo.
CREATE TABLE gaze_quality (
    session_id        INTEGER PRIMARY KEY REFERENCES session (id) ON DELETE CASCADE,
    method            TEXT    NOT NULL,  -- geometric (modelo reajustado) o live (solo suavizado)
    fit_scope         TEXT,              -- calibration o all_targets: con qué se entrenó; NULL en live
    frames            INTEGER NOT NULL,
    check_samples     INTEGER NOT NULL,  -- muestras de validación y comprobaciones de deriva
    camera_delay_ms   REAL    NOT NULL,
    live_error_deg    REAL,
    refined_error_deg REAL,
    drift_corrected   INTEGER NOT NULL,  -- 0/1
    residual_lambda   REAL,
    noise_px          REAL    NOT NULL,  -- ruido de medición usado en el suavizado
    fixations         INTEGER NOT NULL
);


-- =====================================================================
-- Referencias, capturas de pantalla y metadatos
-- =====================================================================

-- Referencia de una tarea, grabada por el evaluador. Los campos JSON siguen
-- contracts/reference.schema.json. Una tarea con referencias no se puede borrar,
-- para no perder por accidente el trabajo del evaluador.
CREATE TABLE reference (
    id                INTEGER PRIMARY KEY,
    task_id           INTEGER NOT NULL REFERENCES task (id),
    source_session_id INTEGER REFERENCES session (id) ON DELETE SET NULL,
    steps             TEXT    NOT NULL,  -- JSON: pasos de la ruta
    candidates        TEXT    NOT NULL,  -- JSON: condiciones finales propuestas
    end_condition     TEXT,              -- JSON: condición confirmada; NULL en borrador
    required_steps    TEXT    NOT NULL,  -- JSON: posiciones de los pasos obligatorios
    status            TEXT    NOT NULL,  -- reference_status
    duration_ms       REAL,
    -- Una grabación guarda a lo sumo una referencia por tarea: volver a
    -- guardarla (doble clic, reintento) no crea un duplicado. El índice de esta
    -- restricción también sirve para buscar las referencias de una tarea.
    UNIQUE (task_id, source_session_id)
);

-- Captura de pantalla de referencia para los fondos de los mapas de calor.
-- La imagen vive en data/captures/; aquí solo su ruta.
CREATE TABLE screen_capture (
    id        INTEGER PRIMARY KEY,
    study_id  INTEGER NOT NULL REFERENCES study (id) ON DELETE CASCADE,
    screen    TEXT    NOT NULL,  -- JSON: { url, title }
    file_path TEXT    NOT NULL,  -- relativa a la carpeta de datos
    t         REAL    NOT NULL
);

-- Captura de lo que se veía en la pestaña evaluada durante una sesión, para
-- la reproducción. Los campos que el estudio no declaró ya vienen tapados. La
-- imagen vive en data/frames/<sesión>/; aquí solo su ruta. Borrar la sesión
-- borra las filas; los archivos se borran con la carpeta de la sesión.
CREATE TABLE session_frame (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    t          REAL    NOT NULL,
    file_path  TEXT    NOT NULL  -- relativa a la carpeta de datos
);

CREATE INDEX session_frame_session_idx ON session_frame (session_id, t);

-- Pares clave-valor de la base de datos.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Versión del esquema. Súbela con cada cambio de este archivo.
INSERT INTO meta (key, value) VALUES ('schema_version', '7');
