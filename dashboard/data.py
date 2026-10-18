"""Acceso a la base de datos desde el panel de resultados (Repository / Facade).

Las páginas nunca escriben SQL: piden los datos a ``DashboardData``, que
devuelve DataFrames listos para mostrar, con los campos JSON ya convertidos a
diccionarios y listas. Las marcas de tiempo quedan en milisegundos desde 1970;
convertirlas para mostrarlas es tarea de la página.

Su única escritura es ``confirm_reference``: confirmar la condición final de
una referencia y marcar sus pasos obligatorios.

No importa Streamlit, para poder probarlo. La caché de Streamlit, si hace
falta, va en las páginas.

Uso::

    with open_data(path) as data:
        sessions = data.get_sessions(study_id=1, versions=["V1", "V2"])
"""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from shared import contracts, db

CONFIRMED = "confirmed"
"""Estado de una referencia confirmada (``reference_status``)."""


class NotFoundError(LookupError):
    """La referencia pedida no existe."""


class InvalidReferenceError(ValueError):
    """La confirmación pedida no cumple el contrato de las referencias."""


@contextmanager
def open_data(path: Path | str) -> Iterator["DashboardData"]:
    """Abre una base para el panel y la cierra al salir del bloque.

    Args:
        path: Archivo de la base.

    Yields:
        Acceso a los datos de esa base.

    Raises:
        FileNotFoundError: Si la base no existe.
        db.SchemaVersionError: Si la versión de su esquema no es la esperada.
    """
    connection = db.open_database(path)
    try:
        yield DashboardData(connection, Path(path).parent)
    finally:
        connection.close()


class DashboardData:
    """Consultas del panel de resultados sobre una base SQLite.

    Args:
        connection: Conexión abierta con ``shared.db.open_database``.
        data_dir: Carpeta de la base, de la que cuelgan las capturas de pantalla.
    """

    def __init__(self, connection: sqlite3.Connection, data_dir: Path) -> None:
        """Guarda la conexión y la carpeta de datos."""
        self._connection = connection
        self._data_dir = data_dir

    # --- Estudios y sesiones ---------------------------------------------------

    def get_studies(self) -> pd.DataFrame:
        """Estudios con su cantidad de sesiones.

        Returns:
            ``id``, ``name``, ``system_under_test``, ``description``, ``sessions``.
        """
        return self._frame(
            "SELECT study.id, name, system_under_test, description, COUNT(session.id) AS sessions"
            " FROM study LEFT JOIN session ON session.study_id = study.id"
            " GROUP BY study.id ORDER BY study.id",
            columns=["id", "name", "system_under_test", "description", "sessions"],
        )

    def get_sessions(
        self,
        study_id: int | None = None,
        versions: Sequence[str] | None = None,
        modes: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Sesiones con su resumen, con filtros opcionales.

        Args:
            study_id: Solo las de este estudio.
            versions: Solo las de estas versiones del sistema evaluado.
            modes: Solo las de estos modos (``session_mode``).

        Returns:
            Una fila por sesión: ``session_id``, ``study_id``, ``study``,
            ``participant_id``, ``version``, ``mode``, ``started_at``,
            ``ended_at``, ``duration_ms`` (vacío si sigue abierta),
            ``incidents``, ``sus_score`` y ``bui`` (vacíos si no hay).
        """
        conditions, params = [], []
        if study_id is not None:
            conditions.append("session.study_id = ?")
            params.append(study_id)
        for column, values in (("version", versions), ("mode", modes)):
            if values:
                conditions.append(f"session.{column} IN ({', '.join('?' * len(values))})")
                params.extend(values)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._frame(
            "SELECT session.id AS session_id, session.study_id, study.name AS study,"
            " participant_id, version, mode, started_at, ended_at,"
            " ROUND(ended_at - started_at, 1) AS duration_ms,"
            " (SELECT COUNT(*) FROM incident WHERE incident.session_id = session.id) AS incidents,"
            " sus_response.score AS sus_score, usability_index.bui"
            " FROM session JOIN study ON study.id = session.study_id"
            " LEFT JOIN sus_response ON sus_response.session_id = session.id"
            " LEFT JOIN usability_index ON usability_index.session_id = session.id"
            f"{where} ORDER BY session.id",
            *params,
            columns=[
                "session_id", "study_id", "study", "participant_id", "version", "mode",
                "started_at", "ended_at", "duration_ms", "incidents", "sus_score", "bui",
            ],
        )  # fmt: skip

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        """Datos generales de una sesión.

        Args:
            session_id: Sesión.

        Returns:
            ``id``, ``study_id``, ``participant_id``, ``version``, ``mode``,
            ``started_at``, ``ended_at``, ``screen_info`` (diccionario),
            ``calibration_error_start`` y ``calibration_error_end``; ``None`` si
            no existe.
        """
        row = self._connection.execute(
            "SELECT id, study_id, participant_id, version, mode, started_at, ended_at,"
            " screen_info, calibration_error_start, calibration_error_end"
            " FROM session WHERE id = ?",
            (_plain(session_id),),
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["screen_info"] = _json(values["screen_info"])
        return values

    # --- Datos de una sesión -----------------------------------------------------

    def get_events(self, session_id: int, types: Sequence[str] | None = None) -> pd.DataFrame:
        """Eventos de una sesión, en orden de tiempo.

        Args:
            session_id: Sesión.
            types: Solo estos tipos de evento (``event_type``).

        Returns:
            ``t``, ``type``, ``x``, ``y``, ``url``, ``title``, ``task_id``,
            ``element`` (diccionario o vacío) y ``data`` (diccionario o vacío).
        """
        filter_sql = f" AND type IN ({', '.join('?' * len(types))})" if types else ""
        frame = self._frame(
            "SELECT t, type, x, y, screen, task_id, element, data FROM event"
            f" WHERE session_id = ?{filter_sql} ORDER BY t, id",
            session_id,
            *(types or ()),
            columns=["t", "type", "x", "y", "screen", "task_id", "element", "data"],
            json_columns=("screen", "element", "data"),
            ints=("task_id",),
        )
        screens = frame.pop("screen")
        frame.insert(4, "url", [item["url"] for item in screens])
        frame.insert(5, "title", [item["title"] for item in screens])
        return frame

    def get_session_tasks(self, session_id: int) -> pd.DataFrame:
        """Tareas de una sesión guiada con su resultado del análisis.

        Args:
            session_id: Sesión.

        Returns:
            ``task_id``, ``position``, ``instruction``, ``t_start``, ``t_end``,
            ``duration_ms``, ``ended_by`` y, si ya se analizó, ``success``,
            ``steps``, ``deviation_step`` y ``off_path_ms``.
        """
        return self._frame(
            "SELECT session_task.task_id, position, instruction, t_start, t_end,"
            " ROUND(t_end - t_start, 1) AS duration_ms, ended_by, success, steps, deviation_step,"
            " off_path_ms"
            " FROM session_task JOIN task ON task.id = session_task.task_id"
            " LEFT JOIN task_result ON task_result.session_id = session_task.session_id"
            " AND task_result.task_id = session_task.task_id"
            " WHERE session_task.session_id = ? ORDER BY t_start",
            session_id,
            columns=[
                "task_id", "position", "instruction", "t_start", "t_end", "duration_ms",
                "ended_by", "success", "steps", "deviation_step", "off_path_ms",
            ],
            ints=("steps", "deviation_step"),
            bools=("success",),
        )  # fmt: skip

    def get_incidents(
        self, session_id: int | None = None, study_id: int | None = None
    ) -> pd.DataFrame:
        """Incidentes de fricción de una sesión o de todo un estudio.

        Args:
            session_id: Solo los de esta sesión.
            study_id: Solo los de las sesiones de este estudio.

        Returns:
            ``session_id``, ``type``, ``t``, ``screen``, ``task_id`` y ``element``.
        """
        conditions, params = [], []
        if session_id is not None:
            conditions.append("incident.session_id = ?")
            params.append(session_id)
        if study_id is not None:
            conditions.append("session.study_id = ?")
            params.append(study_id)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._frame(
            "SELECT incident.session_id, type, t, screen, task_id, element"
            f" FROM incident JOIN session ON session.id = incident.session_id{where}"
            " ORDER BY incident.session_id, t",
            *params,
            columns=["session_id", "type", "t", "screen", "task_id", "element"],
            json_columns=("element",),
            ints=("task_id",),
        )

    def get_episodes(self, session_id: int) -> pd.DataFrame:
        """Episodios de una sesión.

        Args:
            session_id: Sesión.

        Returns:
            ``type``, ``t_start``, ``t_end``, ``duration_ms``, ``screen``,
            ``outcome`` y ``metrics`` (diccionario).
        """
        return self._frame(
            "SELECT type, t_start, t_end, ROUND(t_end - t_start, 1) AS duration_ms, screen,"
            " outcome, metrics"
            " FROM episode WHERE session_id = ? ORDER BY t_start",
            session_id,
            columns=["type", "t_start", "t_end", "duration_ms", "screen", "outcome", "metrics"],
            json_columns=("metrics",),
        )

    def get_face(self, session_id: int) -> pd.DataFrame:
        """Muestras faciales de una sesión.

        Args:
            session_id: Sesión.

        Returns:
            ``t``, ``face_detected``, ``head_yaw``, ``head_pitch`` y ``values``
            (diccionario ``face_value`` → intensidad, o vacío).
        """
        frame = self._frame(
            'SELECT t, face_detected, head_yaw, head_pitch, "values" FROM face_sample'
            " WHERE session_id = ? ORDER BY t",
            session_id,
            columns=["t", "face_detected", "head_yaw", "head_pitch", "values"],
            json_columns=("values",),
            bools=("face_detected",),
        )
        return frame

    def get_gaze(self, session_id: int, *, valid_only: bool = True) -> pd.DataFrame:
        """Muestras de mirada de una sesión.

        Args:
            session_id: Sesión.
            valid_only: Si es verdadero (por defecto), solo las muestras válidas.

        Returns:
            ``t``, ``x``, ``y``, ``scroll_x``, ``scroll_y``, ``element_selector``,
            ``zone`` y ``valid``.
        """
        frame = self._frame(
            "SELECT t, x, y, scroll_x, scroll_y, element_selector, zone, valid FROM gaze_sample"
            f" WHERE session_id = ?{' AND valid = 1' if valid_only else ''} ORDER BY t",
            session_id,
            columns=["t", "x", "y", "scroll_x", "scroll_y", "element_selector", "zone", "valid"],
            bools=("valid",),
        )
        return frame

    # --- Datos de un estudio -----------------------------------------------------

    def get_task_results(self, study_id: int) -> pd.DataFrame:
        """Resultados por tarea de todas las sesiones analizadas de un estudio.

        Args:
            study_id: Estudio.

        Returns:
            ``session_id``, ``participant_id``, ``version``, ``task_id``,
            ``position``, ``instruction``, ``success``, ``duration_ms``,
            ``steps``, ``deviation_step`` y ``off_path_ms``.
        """
        frame = self._frame(
            "SELECT task_result.session_id, participant_id, version, task_result.task_id,"
            " position, instruction, success, duration_ms, steps, deviation_step, off_path_ms"
            " FROM task_result JOIN session ON session.id = task_result.session_id"
            " JOIN task ON task.id = task_result.task_id"
            " WHERE session.study_id = ? ORDER BY position, task_result.session_id",
            study_id,
            columns=[
                "session_id", "participant_id", "version", "task_id", "position", "instruction",
                "success", "duration_ms", "steps", "deviation_step", "off_path_ms",
            ],
            ints=("deviation_step",),
            bools=("success",),
        )  # fmt: skip
        return frame

    def get_screen_summary(self, study_id: int) -> pd.DataFrame:
        """Tiempo e incidentes por pantalla normalizada en un estudio.

        El tiempo sale de los episodios de tipo ``screen``; los incidentes, de
        la tabla de incidentes.

        Args:
            study_id: Estudio.

        Returns:
            Una fila por pantalla, de más a menos incidentes: ``screen``,
            ``visits``, ``sessions``, ``time_ms`` e ``incidents``.
        """
        return self._frame(
            "WITH visits AS ("
            "  SELECT screen, COUNT(*) AS visits, COUNT(DISTINCT episode.session_id) AS sessions,"
            "         ROUND(SUM(t_end - t_start), 1) AS time_ms"
            "  FROM episode JOIN session ON session.id = episode.session_id"
            "  WHERE session.study_id = ? AND type = 'screen' AND screen IS NOT NULL"
            "  GROUP BY screen),"
            " found AS ("
            "  SELECT screen, COUNT(*) AS incidents"
            "  FROM incident JOIN session ON session.id = incident.session_id"
            "  WHERE session.study_id = ? AND screen IS NOT NULL GROUP BY screen)"
            " SELECT screen, COALESCE(visits, 0) AS visits, COALESCE(sessions, 0) AS sessions,"
            "        COALESCE(time_ms, 0) AS time_ms, COALESCE(incidents, 0) AS incidents"
            " FROM (SELECT screen FROM visits UNION SELECT screen FROM found)"
            " LEFT JOIN visits USING (screen) LEFT JOIN found USING (screen)"
            " ORDER BY incidents DESC, screen",
            study_id,
            study_id,
            columns=["screen", "visits", "sessions", "time_ms", "incidents"],
        )

    def get_usability_index(self, study_id: int) -> pd.DataFrame:
        """Índice de usabilidad y SUS de cada sesión analizada de un estudio.

        Args:
            study_id: Estudio.

        Returns:
            ``session_id``, ``participant_id``, ``version``, ``effectiveness``,
            ``time_efficiency``, ``path_efficiency``, ``friction``, ``bui``,
            ``params_version`` y ``sus_score`` (vacío si no respondió el SUS).
        """
        return self._frame(
            "SELECT usability_index.session_id, participant_id, version, effectiveness,"
            " time_efficiency, path_efficiency, friction, bui, params_version,"
            " sus_response.score AS sus_score"
            " FROM usability_index JOIN session ON session.id = usability_index.session_id"
            " LEFT JOIN sus_response ON sus_response.session_id = usability_index.session_id"
            " WHERE session.study_id = ? ORDER BY version, usability_index.session_id",
            study_id,
            columns=[
                "session_id", "participant_id", "version", "effectiveness", "time_efficiency",
                "path_efficiency", "friction", "bui", "params_version", "sus_score",
            ],
        )  # fmt: skip

    # --- Referencias y capturas --------------------------------------------------

    def get_references(self, study_id: int, status: str | None = None) -> pd.DataFrame:
        """Referencias de las tareas de un estudio.

        Args:
            study_id: Estudio.
            status: Solo las de este estado (``draft`` o ``confirmed``).

        Returns:
            ``reference_id``, ``task_id``, ``position``, ``instruction``,
            ``status``, ``source_session_id``, ``steps``, ``candidates``,
            ``end_condition``, ``required_steps`` y ``duration_ms``.
        """
        status_sql = " AND status = ?" if status else ""
        return self._frame(
            "SELECT reference.id AS reference_id, task_id, position, instruction, status,"
            " source_session_id, steps, candidates, end_condition, required_steps, duration_ms"
            " FROM reference JOIN task ON task.id = reference.task_id"
            f" WHERE task.study_id = ?{status_sql} ORDER BY position, reference.id",
            study_id,
            *([status] if status else []),
            columns=[
                "reference_id", "task_id", "position", "instruction", "status",
                "source_session_id", "steps", "candidates", "end_condition", "required_steps",
                "duration_ms",
            ],
            json_columns=("steps", "candidates", "end_condition", "required_steps"),
        )  # fmt: skip

    def get_screen_captures(self, study_id: int) -> pd.DataFrame:
        """Capturas de pantalla de referencia de un estudio (fondos de los mapas de calor).

        Args:
            study_id: Estudio.

        Returns:
            ``capture_id``, ``url``, ``title``, ``t``, ``file_path`` (relativa
            a la carpeta de la base) y ``absolute_path``.
        """
        frame = self._frame(
            "SELECT id AS capture_id, screen, t, file_path FROM screen_capture"
            " WHERE study_id = ? ORDER BY t",
            study_id,
            columns=["capture_id", "screen", "t", "file_path"],
            json_columns=("screen",),
        )
        screens = frame.pop("screen")
        frame.insert(1, "url", [item["url"] for item in screens])
        frame.insert(2, "title", [item["title"] for item in screens])
        frame["absolute_path"] = [str(self._data_dir / path) for path in frame["file_path"]]
        return frame

    def confirm_reference(
        self,
        reference_id: int,
        end_condition: dict[str, Any],
        required_steps: Sequence[int],
    ) -> None:
        """Confirma la condición final de una referencia y marca sus pasos obligatorios.

        Es la única escritura del panel. La referencia queda ``confirmed`` y
        disponible para el modo guiado y la comparación del análisis.

        Args:
            reference_id: Referencia (en borrador o ya confirmada).
            end_condition: Condición final elegida, con la forma de
                ``end_condition`` en ``reference.schema.json``.
            required_steps: Posiciones (desde 0) de los pasos obligatorios
                dentro de ``steps``.

        Raises:
            NotFoundError: Si la referencia no existe.
            InvalidReferenceError: Si la condición o los pasos no cumplen el
                contrato, o una posición no existe en ``steps``.
        """
        row = self._connection.execute(
            "SELECT steps, candidates FROM reference WHERE id = ?", (_plain(reference_id),)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"reference {reference_id} not found")
        steps = json.loads(row["steps"])
        document = {
            "steps": steps,
            "candidates": json.loads(row["candidates"]),
            "end_condition": end_condition,
            "required_steps": list(required_steps),
        }
        errors = contracts.validate("reference", document)
        if errors:
            raise InvalidReferenceError(f"reference {reference_id}: {errors[0]}")
        outside = [position for position in required_steps if position >= len(steps)]
        if outside:
            raise InvalidReferenceError(
                f"reference {reference_id}: required steps {outside} are not in its"
                f" {len(steps)} steps"
            )
        with db.transaction(self._connection):
            self._connection.execute(
                "UPDATE reference SET end_condition = ?, required_steps = ?, status = ?"
                " WHERE id = ?",
                (
                    json.dumps(end_condition, ensure_ascii=False),
                    json.dumps(list(required_steps)),
                    CONFIRMED,
                    _plain(reference_id),
                ),
            )

    # --- Interno -----------------------------------------------------------------

    def _frame(
        self,
        sql: str,
        *params: Any,
        columns: Sequence[str],
        json_columns: Sequence[str] = (),
        ints: Sequence[str] = (),
        bools: Sequence[str] = (),
    ) -> pd.DataFrame:
        """Ejecuta una consulta y la devuelve como DataFrame, con los JSON convertidos.

        Con ``columns`` explícitas, un resultado vacío conserva sus columnas.
        ``ints`` y ``bools`` pasan a tipos que admiten vacíos (``Int64``,
        ``boolean``), para que un ``NULL`` no convierta los enteros en decimales.
        """
        positions = [columns.index(column) for column in json_columns]
        rows = []
        for row in self._connection.execute(sql, [_plain(value) for value in params]):
            values = list(row)
            # Se convierten antes de armar el DataFrame: pandas cambiaría NULL por NaN.
            for position in positions:
                values[position] = _json(values[position])
            rows.append(values)
        frame = pd.DataFrame.from_records(rows, columns=list(columns))
        for column in json_columns:
            frame[column] = frame[column].astype(object)
        for column in ints:
            frame[column] = frame[column].astype("Int64")
        for column in bools:
            frame[column] = frame[column].astype("boolean")
        return frame


def _plain(value: Any) -> Any:
    """Convierte un valor de NumPy en el tipo de Python equivalente.

    Los id que salen de un DataFrame son ``numpy.int64``; ``sqlite3`` los
    enlazaría como datos binarios y la consulta no encontraría nada, sin error.
    """
    return value.item() if isinstance(value, np.generic) else value


def _json(text: str | None) -> Any:
    """Convierte un campo JSON de la base; ``NULL`` queda ``None``."""
    return None if text is None else json.loads(text)
