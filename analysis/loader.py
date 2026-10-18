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
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from analysis import columns
from shared import db

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

        Raises:
            columns.ColumnValidationError: Si algún DataFrame no cumple su tabla.
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
        with db.transaction(self._connection):
            for table in columns.RESULT_TABLES:
                self._connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            for table, df in results.items():
                extra = {"params_version": params_version} if table == "usability_index" else {}
                self._insert(table, session_id, df, extra)

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
