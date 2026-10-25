"""Etapa 6 del análisis: índice de usabilidad conductual (``bui``).

Calcula, en las sesiones guiadas, a partir de los resultados por tarea y de
los incidentes (cada componente de 0 a 100):

- ``effectiveness``: tareas completadas sobre tareas asignadas;
- ``time_efficiency``: promedio de ``min(1, t_ref / t_usuario)`` sobre las
  tareas completadas;
- ``path_efficiency``: lo mismo con los pasos;
- ``friction``: ``1 - min(1, i / params.friction_i_max)``, con ``i`` los
  incidentes por minuto de tarea;
- ``bui``: promedio de los cuatro componentes.

Si no se completó ninguna tarea, las dos eficiencias valen 0. En el modo libre
no se calcula el índice. La versión de los parámetros la agrega el repositorio
al guardar.

Sin umbral de fricción, resultados completos o referencias válidas para las
tareas completadas, devuelve una tabla vacía. Si hay varias referencias,
usa la mayor duración y la mayor cantidad de pasos válidas para cada tarea,
aceptando las rutas alternativas como en el detector de tarea excedida.
"""

import math

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters


def compute(
    data: SessionData, task_results: pd.DataFrame, incidents: pd.DataFrame, params: Parameters
) -> pd.DataFrame:
    """Calcula el índice de una sesión.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        task_results: Resultados por tarea (tabla ``task_result``).
        incidents: Incidentes de la sesión (tabla ``incident``).
        params: Parámetros del análisis.

    Returns:
        Una fila con las columnas de ``usability_index``, o ninguna si la sesión
        no es guiada o no se puede calcular.
    """
    if data.session.mode != "guided" or params.friction_i_max is None:
        return columns.empty("usability_index")
    if not math.isfinite(params.friction_i_max) or params.friction_i_max <= 0:
        return columns.empty("usability_index")
    columns.validate(task_results, "task_result")
    columns.validate(incidents, "incident")
    task_ids = set(data.tasks["task_id"])
    if not task_ids or set(task_results["task_id"]) != task_ids:
        return columns.empty("usability_index")
    if (
        not task_results["duration_ms"].map(math.isfinite).all()
        or (task_results["duration_ms"] < 0).any()
        or (task_results["steps"] < 0).any()
    ):
        return columns.empty("usability_index")
    minutes = task_results["duration_ms"].sum() / 60_000
    if not math.isfinite(minutes) or minutes <= 0:
        return columns.empty("usability_index")

    references: dict[int, tuple[float, int]] = {}
    for reference in data.references.itertuples():
        duration = reference.duration_ms
        steps = len(reference.steps)
        if (
            columns.is_missing(duration)
            or not math.isfinite(duration)
            or duration <= 0
            or not steps
        ):
            continue
        previous = references.get(reference.task_id, (0.0, 0))
        references[reference.task_id] = (max(previous[0], duration), max(previous[1], steps))

    completed = task_results[task_results["success"]]
    time_ratios, path_ratios = [], []
    for task in completed.itertuples():
        baseline = references.get(task.task_id)
        if baseline is None or task.duration_ms <= 0 or task.steps <= 0:
            return columns.empty("usability_index")
        time_ratios.append(min(1.0, baseline[0] / task.duration_ms))
        path_ratios.append(min(1.0, baseline[1] / task.steps))

    effectiveness = 100 * len(completed) / len(task_results)
    time_efficiency = 100 * sum(time_ratios) / len(completed) if len(completed) else 0.0
    path_efficiency = 100 * sum(path_ratios) / len(completed) if len(completed) else 0.0
    per_minute = incidents["task_id"].isin(task_ids).sum() / minutes
    friction = 100 * (1 - min(1.0, per_minute / params.friction_i_max))
    return columns.frame(
        "usability_index",
        [
            {
                "effectiveness": effectiveness,
                "time_efficiency": time_efficiency,
                "path_efficiency": path_efficiency,
                "friction": friction,
                "bui": (effectiveness + time_efficiency + path_efficiency + friction) / 4,
            }
        ],
    )
