"""Lectura de los resultados de un estudio analizado, para evaluarlo.

Solo lee: sesiones guiadas cerradas, sus tareas, resultados, incidentes, índice
y SUS. La evaluación no escribe en la base.
"""

import sqlite3
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StudyResults:
    """Resultados de las sesiones guiadas de un estudio.

    Attributes:
        sessions: ``session_id``, ``participant_id``, ``version`` y ``sus`` (o nulo).
        tasks: ``task_id`` y ``position`` de cada tarea del estudio.
        task_results: Tabla ``task_result`` con ``position``.
        incidents: Tabla ``incident`` (sin elemento) con ``position`` (nula fuera de las tareas).
        index: Tabla ``usability_index`` de esas sesiones.
    """

    sessions: pd.DataFrame
    tasks: pd.DataFrame
    task_results: pd.DataFrame
    incidents: pd.DataFrame
    index: pd.DataFrame


def load_study_results(connection: sqlite3.Connection, study_id: int) -> StudyResults:
    """Carga los resultados de las sesiones guiadas y cerradas de un estudio.

    Args:
        connection: Conexión a la base.
        study_id: Estudio.

    Returns:
        Resultados del estudio.

    Raises:
        LookupError: Si el estudio no existe.
    """
    if connection.execute("SELECT 1 FROM study WHERE id = ?", (study_id,)).fetchone() is None:
        raise LookupError(f"study {study_id} does not exist")

    def frame(query: str, columns: list[str]) -> pd.DataFrame:
        return pd.DataFrame(connection.execute(query, (study_id,)).fetchall(), columns=columns)

    guided = (
        "SELECT id FROM session WHERE study_id = ? AND mode = 'guided' AND ended_at IS NOT NULL"
    )
    sessions = frame(
        "SELECT s.id, s.participant_id, s.version, r.score FROM session s"
        " LEFT JOIN sus_response r ON r.session_id = s.id"
        " WHERE s.study_id = ? AND s.mode = 'guided' AND s.ended_at IS NOT NULL ORDER BY s.id",
        ["session_id", "participant_id", "version", "sus"],
    )
    tasks = frame(
        "SELECT id, position FROM task WHERE study_id = ? ORDER BY position",
        ["task_id", "position"],
    )
    task_results = frame(
        "SELECT session_id, task_id, success, duration_ms, steps, deviation_step, off_path_ms"
        f" FROM task_result WHERE session_id IN ({guided})",
        [
            "session_id",
            "task_id",
            "success",
            "duration_ms",
            "steps",
            "deviation_step",
            "off_path_ms",
        ],
    )
    incidents = frame(
        f"SELECT session_id, type, t, screen, task_id FROM incident WHERE session_id IN ({guided})",
        ["session_id", "type", "t", "screen", "task_id"],
    )
    index = frame(
        "SELECT session_id, effectiveness, time_efficiency, path_efficiency, friction, bui,"
        f" params_version FROM usability_index WHERE session_id IN ({guided})",
        [
            "session_id",
            "effectiveness",
            "time_efficiency",
            "path_efficiency",
            "friction",
            "bui",
            "params_version",
        ],
    )
    positions = dict(zip(tasks["task_id"], tasks["position"], strict=True))
    task_results["success"] = task_results["success"].astype(bool)
    task_results["position"] = task_results["task_id"].map(positions)
    incidents["position"] = incidents["task_id"].map(positions).astype("Int64")
    return StudyResults(sessions, tasks, task_results, incidents, index)
