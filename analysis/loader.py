"""Acceso a la base de datos desde el análisis (Repository).

Las etapas no leen ni escriben la base: reciben un ``SessionData`` y devuelven
DataFrames. Este módulo es el único del análisis que tiene SQL:

- ``load_session`` arma el ``SessionData`` de una sesión, con los campos JSON ya
  convertidos;
- ``list_sessions`` lista las sesiones de un estudio;
- ``save_results`` guarda los resultados de una sesión. Es idempotente: borra
  los resultados previos de la sesión y escribe los nuevos en una sola
  transacción, así volver a analizar nunca duplica filas.

``AnalysisRepository`` es la interfaz que usa el orquestador;
``SqliteAnalysisRepository``, la implementación sobre SQLite. Las pruebas pueden
sustituirla por cualquier objeto con las mismas funciones.
"""

import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from analysis import columns
from analysis.gaze.attention import ACTIVITY_TYPES
from shared import contracts, db

CONFIRMED_REFERENCE = "confirmed"
"""Estado de las referencias que usa el análisis (``reference_status``)."""

SESSION_FRAMES = ("events", "gaze", "face", "calibrations", "tasks", "references")
"""DataFrames de ``SessionData``; cada uno se valida contra la tabla del mismo nombre."""


class NotFoundError(LookupError):
    """La sesión o el estudio pedido no existe."""


@dataclass(frozen=True)
class SessionInfo:
    """Datos generales de una sesión.

    Attributes:
        id: Id de la sesión.
        study_id: Estudio de la sesión.
        participant_id: Código anónimo del participante.
        version: Versión del sistema evaluado (V0, V1…).
        mode: Modo de la sesión (``session_mode``).
        started_at: Inicio, en ms desde 1970.
        ended_at: Cierre, o ``None`` si la sesión sigue abierta.
        screen_info: Tamaño de ventana y pantalla, ``devicePixelRatio`` y
            versión de Chrome, o ``None``.
    """

    id: int
    study_id: int
    participant_id: str
    version: str
    mode: str
    started_at: float
    ended_at: float | None
    screen_info: Mapping[str, Any] | None

    @property
    def closed(self) -> bool:
        """Indica si la sesión ya se cerró."""
        return self.ended_at is not None


@dataclass(frozen=True)
class SessionData:
    """Todo lo capturado en una sesión, como lo reciben las etapas.

    Las columnas de cada DataFrame están en ``analysis/columns.py`` (tabla del
    mismo nombre). Los campos JSON ya son diccionarios o listas. Una etapa que
    cambia los datos devuelve una copia con ``dataclasses.replace``; nunca
    modifica estos DataFrames.

    Attributes:
        session: Datos generales de la sesión.
        events: Eventos de interacción, ordenados por tiempo. ``screen`` es la
            URL hasta que la etapa de pantallas la normaliza.
        gaze: Muestras de mirada.
        face: Muestras faciales; ``values`` es un diccionario ``face_value`` → intensidad.
        calibrations: Calibraciones de mirada.
        tasks: Inicio y fin de cada tarea del modo guiado.
        references: Referencias confirmadas de las tareas del estudio.
    """

    session: SessionInfo
    events: pd.DataFrame
    gaze: pd.DataFrame
    face: pd.DataFrame
    calibrations: pd.DataFrame
    tasks: pd.DataFrame
    references: pd.DataFrame


def validate_session_data(data: Any, *, label: str = "session data") -> None:
    """Comprueba que un ``SessionData`` tenga sus DataFrames con las columnas base.

    Args:
        data: Objeto a comprobar.
        label: Qué lo produjo, para el mensaje.

    Raises:
        TypeError: Si no es un ``SessionData``.
        columns.ColumnValidationError: Si algún DataFrame no cumple su tabla.
    """
    if not isinstance(data, SessionData):
        raise TypeError(f"{label}: expected SessionData, got {type(data).__name__}")
    for name in SESSION_FRAMES:
        columns.validate(getattr(data, name), name, label=f"{label} ({name})")


@dataclass(frozen=True)
class GazeInputs:
    """Lo que necesitan la medición, el reprocesamiento y la atribución de la mirada.

    Las columnas de cada DataFrame están en ``analysis/columns.py`` (tablas
    ``gaze_features``, ``gaze_targets``, ``gaze_calibrations``, ``layouts``,
    ``gaze`` y ``gaze_interactions``). Los campos JSON ya son diccionarios o listas.

    Attributes:
        session: Datos generales de la sesión.
        features: Características de mirada de cada cuadro, en orden de tiempo.
        targets: Puntos que se pidió mirar, con su tramo de tiempo.
        calibrations: Calibraciones, validaciones y comprobaciones de deriva.
        layouts: Disposición de cada pantalla, en orden de tiempo.
        gaze: Muestras de mirada registradas en vivo.
        interactions: Clics, focos y eventos de actividad, con el selector de su
            elemento si lo tienen, en orden de tiempo.
    """

    session: SessionInfo
    features: pd.DataFrame
    targets: pd.DataFrame
    calibrations: pd.DataFrame
    layouts: pd.DataFrame
    gaze: pd.DataFrame
    interactions: pd.DataFrame = field(default_factory=lambda: columns.empty("gaze_interactions"))


class GazeRepository(Protocol):
    """Lo que la mirada necesita de la base de datos (separado del resto del análisis)."""

    def load_gaze_inputs(self, session_id: int) -> GazeInputs:
        """Carga los datos de mirada de una sesión; falla con ``NotFoundError`` si no existe."""
        ...

    def save_gaze_refinement(
        self, session_id: int, samples: pd.DataFrame, quality: pd.DataFrame
    ) -> None:
        """Reemplaza la mirada reprocesada de una sesión, todo o nada."""
        ...

    def save_gaze_attention(
        self, session_id: int, fixations: pd.DataFrame, candidates: pd.DataFrame
    ) -> None:
        """Reemplaza la atribución de la mirada de una sesión, todo o nada."""
        ...


class AnalysisRepository(Protocol):
    """Lo que el análisis necesita de la base de datos."""

    def load_session(self, session_id: int) -> SessionData:
        """Carga todo lo capturado en una sesión.

        Raises:
            NotFoundError: Si la sesión no existe.
        """
        ...

    def list_sessions(self, study_id: int) -> list[SessionInfo]:
        """Lista las sesiones de un estudio, en orden de id.

        Raises:
            NotFoundError: Si el estudio no existe.
        """
        ...

    def save_results(
        self,
        session_id: int,
        episodes: pd.DataFrame,
        incidents: pd.DataFrame,
        task_results: pd.DataFrame,
        usability_index: pd.DataFrame,
        params_version: str,
        *,
        reference_drafts: pd.DataFrame | None = None,
    ) -> None:
        """Reemplaza los resultados de una sesión por los nuevos.

        Raises:
            columns.ColumnValidationError: Si algún DataFrame no cumple su tabla.
        """
        ...


class SqliteAnalysisRepository:
    """Repositorio del análisis sobre una base SQLite.

    Args:
        connection: Conexión abierta con ``shared.db.open_database``. Quien la
            abre la cierra.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Guarda la conexión."""
        self._connection = connection

    def load_session(self, session_id: int) -> SessionData:
        """Carga todo lo capturado en una sesión.

        Args:
            session_id: Sesión a cargar.

        Returns:
            Datos de la sesión, con los JSON convertidos.

        Raises:
            NotFoundError: Si la sesión no existe.
        """
        row = self._connection.execute(_SESSION_SQL + " WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"session {session_id} not found")
        session = _session_info(row)
        return SessionData(
            session=session,
            events=columns.frame("events", map(_event, self._rows(_EVENTS_SQL, session_id))),
            gaze=columns.frame("gaze", self._rows(_GAZE_SQL, session_id)),
            face=columns.frame("face", map(_face, self._rows(_FACE_SQL, session_id))),
            calibrations=columns.frame("calibrations", self._rows(_CALIBRATIONS_SQL, session_id)),
            tasks=columns.frame("tasks", self._rows(_TASKS_SQL, session_id)),
            references=columns.frame(
                "references",
                map(_reference, self._rows(_REFERENCES_SQL, session.study_id, CONFIRMED_REFERENCE)),
            ),
        )

    def load_gaze_inputs(self, session_id: int) -> GazeInputs:
        """Carga los datos de mirada de una sesión.

        Args:
            session_id: Sesión a cargar.

        Returns:
            Cuadros, objetivos, calibraciones, disposiciones y muestras de mirada.

        Raises:
            NotFoundError: Si la sesión no existe.
        """
        row = self._connection.execute(_SESSION_SQL + " WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"session {session_id} not found")
        return GazeInputs(
            session=_session_info(row),
            features=columns.frame("gaze_features", self._rows(_GAZE_FEATURES_SQL, session_id)),
            targets=columns.frame(
                "gaze_targets", map(_gaze_target, self._rows(_GAZE_TARGETS_SQL, session_id))
            ),
            calibrations=columns.frame(
                "gaze_calibrations", self._rows(_GAZE_CALIBRATIONS_SQL, session_id)
            ),
            layouts=columns.frame("layouts", map(_layout, self._rows(_LAYOUTS_SQL, session_id))),
            gaze=columns.frame("gaze", self._rows(_GAZE_SQL, session_id)),
            interactions=columns.frame(
                "gaze_interactions",
                map(_interaction, self._rows(_INTERACTIONS_SQL, session_id)),
            ),
        )

    def save_gaze_refinement(
        self, session_id: int, samples: pd.DataFrame, quality: pd.DataFrame
    ) -> None:
        """Reemplaza la mirada reprocesada de una sesión, todo o nada.

        Args:
            session_id: Sesión reprocesada.
            samples: Una fila por cuadro (tabla ``gaze_refined``).
            quality: Una fila o ninguna (tabla ``gaze_quality``).

        Raises:
            columns.ColumnValidationError: Si alguna tabla no cumple su especificación;
                en ese caso no se toca la base.
        """
        tables = dict(zip(columns.GAZE_RESULT_TABLES, (samples, quality), strict=True))
        for table, df in tables.items():
            columns.validate(df, table)
        with db.transaction(self._connection):
            for table, df in tables.items():
                self._connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                self._insert(table, session_id, df, {})

    def save_gaze_attention(
        self, session_id: int, fixations: pd.DataFrame, candidates: pd.DataFrame
    ) -> None:
        """Reemplaza la atribución de la mirada de una sesión, todo o nada.

        Args:
            session_id: Sesión.
            fixations: Una fila por fijación (tabla ``gaze_fixation``).
            candidates: Candidatos de cada fijación (tabla ``gaze_attribution``).

        Raises:
            columns.ColumnValidationError: Si alguna tabla no cumple su especificación;
                en ese caso no se toca la base.
        """
        tables = dict(zip(columns.GAZE_ATTENTION_TABLES, (fixations, candidates), strict=True))
        for table, df in tables.items():
            columns.validate(df, table)
        with db.transaction(self._connection):
            for table, df in tables.items():
                self._connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                self._insert(table, session_id, df, {})

    def load_gaze_attention(self, session_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Carga fijaciones y candidatos ya analizados para medirlos sin recalcularlos.

        Args:
            session_id: Sesión existente; su existencia se verifica al cargar sus entradas.

        Returns:
            Tablas gaze_fixation y gaze_attribution, sin session_id.
        """
        return tuple(
            columns.frame(
                table,
                self._rows(
                    f"SELECT {', '.join(columns.spec(table).columns)} FROM {table}"
                    " WHERE session_id = ? ORDER BY fixation",
                    session_id,
                ),
            )
            for table in columns.GAZE_ATTENTION_TABLES
        )

    def load_gaze_states(self, session_id: int) -> pd.DataFrame:
        """Carga estados de mirada, incluidas las muestras que no forman fijación."""
        return pd.DataFrame(
            self._rows(
                "SELECT t, state FROM gaze_sample WHERE session_id = ?"
                " AND state IS NOT NULL ORDER BY t",
                session_id,
            ),
            columns=["t", "state"],
        )

    def load_facial_labels(self, session_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Carga incidentes y resultados como etiquetas débiles, sin usarlos como rasgos."""
        return tuple(
            columns.frame(
                table,
                self._rows(
                    f"SELECT {', '.join(columns.spec(table).columns)} FROM {table}"
                    " WHERE session_id = ?",
                    session_id,
                ),
            )
            for table in ("incident", "task_result")
        )

    def list_sessions(self, study_id: int) -> list[SessionInfo]:
        """Lista las sesiones de un estudio.

        Args:
            study_id: Estudio.

        Returns:
            Sesiones del estudio en orden de id, abiertas y cerradas.

        Raises:
            NotFoundError: Si el estudio no existe.
        """
        if (
            self._connection.execute("SELECT 1 FROM study WHERE id = ?", (study_id,)).fetchone()
            is None
        ):
            raise NotFoundError(f"study {study_id} not found")
        rows = self._connection.execute(
            _SESSION_SQL + " WHERE study_id = ? ORDER BY id", (study_id,)
        )
        return [_session_info(row) for row in rows]

    def save_results(
        self,
        session_id: int,
        episodes: pd.DataFrame,
        incidents: pd.DataFrame,
        task_results: pd.DataFrame,
        usability_index: pd.DataFrame,
        params_version: str,
        *,
        reference_drafts: pd.DataFrame | None = None,
    ) -> None:
        """Reemplaza los resultados de una sesión, todo o nada.

        Valida los cuatro DataFrames antes de tocar la base: si alguno es
        incorrecto, los resultados previos quedan como estaban.

        Args:
            session_id: Sesión analizada.
            episodes: Episodios (tabla ``episode``).
            incidents: Incidentes (tabla ``incident``).
            task_results: Resultados por tarea (tabla ``task_result``).
            usability_index: Índice de la sesión, una fila o ninguna (tabla
                ``usability_index``).
            params_version: Versión de los parámetros; se guarda con el índice.
            reference_drafts: Rutas y candidatas extraídas de una grabación de
                referencia. Se guardan en la misma transacción y se conservan
                las referencias que ya están confirmadas.

        Raises:
            columns.ColumnValidationError: Si algún DataFrame no cumple su tabla.
            ValueError: Si un borrador no cumple el contrato o no pertenece a una
                tarea de la grabación de referencia.
        """
        results = dict(
            zip(
                columns.RESULT_TABLES,
                (episodes, incidents, task_results, usability_index),
                strict=True,
            )
        )
        for table, df in results.items():
            columns.validate(df, table)
        if reference_drafts is not None:
            _validate_reference_drafts(reference_drafts)
        with db.transaction(self._connection):
            if reference_drafts is not None and not reference_drafts.empty:
                self._save_reference_drafts(session_id, reference_drafts)
            for table in columns.RESULT_TABLES:
                self._connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            for table, df in results.items():
                extra = {"params_version": params_version} if table == "usability_index" else {}
                self._insert(table, session_id, df, extra)

    def _save_reference_drafts(self, session_id: int, drafts: pd.DataFrame) -> None:
        """Actualiza borradores de la grabación sin sobrescribir confirmaciones."""
        session = self._connection.execute(
            "SELECT study_id, mode FROM session WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None or session["mode"] != "reference":
            raise ValueError("reference drafts require a reference recording session")
        task_ids = {
            row[0]
            for row in self._connection.execute(
                "SELECT task.id FROM task JOIN session_task ON session_task.task_id = task.id"
                " WHERE session_task.session_id = ? AND task.study_id = ?",
                (session_id, session["study_id"]),
            )
        }
        if not set(drafts["task_id"]).issubset(task_ids):
            raise ValueError("reference drafts must belong to recorded tasks of the session study")
        self._connection.executemany(
            "INSERT INTO reference (task_id, source_session_id, steps, candidates,"
            " end_condition, required_steps, status, duration_ms)"
            " VALUES (?, ?, ?, ?, NULL, '[]', 'draft', ?)"
            " ON CONFLICT (task_id, source_session_id) DO UPDATE SET"
            " steps = excluded.steps, candidates = excluded.candidates,"
            " duration_ms = excluded.duration_ms WHERE reference.status = 'draft'",
            [
                (
                    int(row.task_id),
                    session_id,
                    json.dumps(row.steps, ensure_ascii=False),
                    json.dumps(row.candidates, ensure_ascii=False),
                    float(row.duration_ms),
                )
                for row in drafts.itertuples()
            ],
        )

    def _rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        """Ejecuta una consulta y devuelve sus filas como diccionarios."""
        return [dict(row) for row in self._connection.execute(sql, params)]

    def _insert(self, table: str, session_id: int, df: pd.DataFrame, extra: dict[str, Any]) -> None:
        """Inserta las filas de un DataFrame de resultados con su ``session_id``."""
        spec = columns.spec(table).columns
        names = ["session_id", *spec, *extra]
        sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"
        rows = [
            (session_id, *(_db_value(spec[name], record[name]) for name in spec), *extra.values())
            for record in df.to_dict("records")
        ]
        self._connection.executemany(sql, rows)


# Consultas. Los datos de captura se leen en orden de tiempo; el id desempata.
_SESSION_SQL = (
    "SELECT id, study_id, participant_id, version, mode, started_at, ended_at, screen_info"
    " FROM session"
)
_EVENTS_SQL = (
    "SELECT t, type, x, y, screen, task_id, element, data FROM event"
    " WHERE session_id = ? ORDER BY t, id"
)
_GAZE_SQL = (
    "SELECT t, x, y, scroll_x, scroll_y, element_selector, zone, valid FROM gaze_sample"
    " WHERE session_id = ? ORDER BY t"
)
_FACE_SQL = (
    'SELECT t, "values", head_yaw, head_pitch, face_detected FROM face_sample'
    " WHERE session_id = ? ORDER BY t"
)
_CALIBRATIONS_SQL = (
    "SELECT t, type, error_px, error_deg, accepted, camera_delay_ms FROM calibration"
    " WHERE session_id = ? ORDER BY t"
)
_GAZE_FEATURES_SQL = "SELECT * FROM gaze_feature WHERE session_id = ? ORDER BY t"
_GAZE_TARGETS_SQL = (
    'SELECT t, t_end, calibration_type, phase, "group", viewport_width, viewport_height, points'
    " FROM gaze_target WHERE session_id = ? ORDER BY t"
)
_GAZE_CALIBRATIONS_SQL = (
    "SELECT t, type, error_px, error_deg, accepted, camera_delay_ms, viewing_distance_cm,"
    " css_px_per_cm,"
    " precision_deg, return_error_deg, estimator, corrected, correction_x_px, correction_y_px"
    " FROM calibration WHERE session_id = ? ORDER BY t"
)
_LAYOUTS_SQL = (
    "SELECT t, screen, viewport_width, viewport_height, scroll_x, scroll_y, regions, elements,"
    " truncated FROM page_layout WHERE session_id = ? ORDER BY t"
)
_INTERACTIONS_SQL = (
    "SELECT t, type, element FROM event WHERE session_id = ? AND type IN ("
    + ", ".join(f"'{name}'" for name in ACTIVITY_TYPES)
    + ") ORDER BY t, id"
)
_TASKS_SQL = (
    "SELECT task_id, t_start, t_end, ended_by FROM session_task"
    " WHERE session_id = ? ORDER BY t_start"
)
_REFERENCES_SQL = (
    "SELECT reference.id, reference.task_id, steps, end_condition, required_steps, duration_ms"
    " FROM reference JOIN task ON task.id = reference.task_id"
    " WHERE task.study_id = ? AND reference.status = ? ORDER BY reference.id"
)


def _json(text: str | None) -> Any:
    """Convierte un campo JSON de la base; ``NULL`` queda ``None``."""
    return None if text is None else json.loads(text)


def _session_info(row: sqlite3.Row) -> SessionInfo:
    """Convierte una fila de ``session``."""
    values = dict(row)
    values["screen_info"] = _json(values["screen_info"])
    return SessionInfo(**values)


def _event(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila de ``event``: separa la pantalla en URL y título."""
    screen = json.loads(row["screen"])
    return {
        **row,
        "url": screen["url"],
        "title": screen["title"],
        "screen": screen["url"],
        "element": _json(row["element"]),
        "data": _json(row["data"]),
    }


def _face(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila de ``face_sample``."""
    return {**row, "values": _json(row["values"])}


def _gaze_target(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila de ``gaze_target``."""
    return {**row, "points": _json(row["points"])}


def _layout(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila de ``page_layout``."""
    return {
        **row,
        "screen": _json(row["screen"]),
        "regions": _json(row["regions"]),
        "elements": _json(row["elements"]),
    }


def _interaction(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila de ``event`` en una interacción: solo el selector del elemento."""
    element = _json(row["element"])
    selector = element.get("selector") if isinstance(element, dict) else None
    return {"t": row["t"], "type": row["type"], "selector": selector}


def _reference(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte una fila de ``reference``."""
    return {
        **row,
        "steps": _json(row["steps"]),
        "end_condition": _json(row["end_condition"]),
        "required_steps": _json(row["required_steps"]),
    }


def _db_value(column: columns.Column, value: Any) -> Any:
    """Convierte una celda de pandas al valor que se guarda en SQLite."""
    if columns.is_missing(value):
        return None
    if column.kind == "json":
        return json.dumps(value, ensure_ascii=False)
    if column.kind == "bool":
        return int(bool(value))
    if column.kind == "int":
        return int(value)
    if column.kind == "float":
        return float(value)
    return str(value)


def _validate_reference_drafts(drafts: pd.DataFrame) -> None:
    """Revisa las columnas y el contrato JSON antes de escribir resultados."""
    columns.validate(drafts, "reference_draft")
    for row in drafts.itertuples():
        document = {
            "steps": row.steps,
            "candidates": row.candidates,
            "end_condition": None,
            "required_steps": [],
        }
        errors = contracts.validate("reference", document)
        if errors:
            raise ValueError(f"reference draft for task {row.task_id}: {errors[0]}")
        if not math.isfinite(row.duration_ms) or row.duration_ms < 0:
            raise ValueError(f"reference draft for task {row.task_id}: invalid duration_ms")
