"""IUC de cada sesión, completo y por mitades de las tareas (P1).

Se recalcula con la misma función del análisis (``analysis.usability_index``)
para que la evaluación use un único ``friction_i_max`` en todas las sesiones y
pueda calcular el índice con solo una parte de las tareas (consistencia por
mitades).
"""

import dataclasses
from collections.abc import Sequence

import pandas as pd

from analysis import columns, usability_index
from analysis.loader import AnalysisRepository, SessionData
from analysis.parameters import Parameters
from scripts.evaluation.repository import StudyResults

COMPONENTS = ("effectiveness", "time_efficiency", "path_efficiency", "friction", "bui")
"""Componentes del índice, en el orden de la tabla ``usability_index``."""

DEFAULT_HALVES = ((1, 3), (2, 4))
"""Mitades de las tareas para la consistencia: posiciones impares y pares."""


def session_indexes(
    repository: AnalysisRepository,
    results: StudyResults,
    params: Parameters,
    halves: Sequence[Sequence[int]] = DEFAULT_HALVES,
) -> pd.DataFrame:
    """IUC de cada sesión guiada: con todas las tareas y con cada mitad.

    Args:
        repository: Acceso a los datos de cada sesión (tareas y referencias).
        results: Resultados del estudio.
        params: Parámetros del análisis, con ``friction_i_max`` definido.
        halves: Posiciones de las tareas de cada mitad.

    Returns:
        Una fila por sesión con ``session_id``, ``participant_id``, ``version``,
        ``sus``, los componentes del índice y ``bui_half_1``, ``bui_half_2``…
        Una sesión sin índice calculable queda con los valores nulos.

    Raises:
        ValueError: Si ``friction_i_max`` no está definido.
    """
    if params.friction_i_max is None:
        raise ValueError(
            "friction_i_max is not set in parameters.yaml;"
            " pass --friction-i-max to evaluate the index"
        )
    rows = []
    for session in results.sessions.itertuples():
        data = repository.load_session(int(session.session_id))
        own_results = results.task_results[results.task_results["session_id"] == session.session_id]
        own_incidents = results.incidents[results.incidents["session_id"] == session.session_id]
        row = {
            "session_id": int(session.session_id),
            "participant_id": session.participant_id,
            "version": session.version,
            "sus": session.sus,
        }
        row |= _index(data, own_results, own_incidents, params, positions=None)
        for number, half in enumerate(halves, start=1):
            row[f"bui_half_{number}"] = _index(
                data, own_results, own_incidents, params, positions=tuple(half)
            )["bui"]
        rows.append(row)
    return pd.DataFrame(rows)


def _index(
    data: SessionData,
    task_results: pd.DataFrame,
    incidents: pd.DataFrame,
    params: Parameters,
    positions: tuple[int, ...] | None,
) -> dict[str, float | None]:
    """Índice con todas las tareas o solo con las de ``positions``."""
    chosen = (
        task_results
        if positions is None
        else task_results[task_results["position"].isin(positions)]
    )
    tasks = data.tasks[data.tasks["task_id"].isin(chosen["task_id"])]
    subset = dataclasses.replace(data, tasks=tasks)
    task_table = columns.frame(
        "task_result", chosen[list(columns.spec("task_result").columns)].to_dict("records")
    )
    own = incidents if positions is None else incidents[incidents["position"].isin(positions)]
    incident_table = columns.frame(
        "incident",
        [
            {
                "type": row.type,
                "t": row.t,
                "screen": row.screen,
                "task_id": None if pd.isna(row.task_id) else int(row.task_id),
                "element": None,
            }
            for row in own.itertuples()
        ],
    )
    if chosen.empty:
        return dict.fromkeys(COMPONENTS)
    computed = usability_index.compute(subset, task_table, incident_table, params)
    if computed.empty:
        return dict.fromkeys(COMPONENTS)
    return {name: float(computed.iloc[0][name]) for name in COMPONENTS}
