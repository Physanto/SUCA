"""Etiquetas de las ventanas: ¿la persona está ante un problema sembrado?

Una ventana vale 1 si en ella la persona está en la tarea y la pantalla de un
problema sembrado **activo en su versión** (según el catálogo de
``shared/problems.py``). Las mismas tareas y pantallas en una versión sin el
problema valen 0. La etiqueta viene del diseño del experimento, no de los
detectores: así la comparación entre el modelo y las reglas no es circular.

Para comparar con las reglas, cada ventana indica además si los detectores
informaron algún incidente en ella.
"""

from collections.abc import Mapping

import pandas as pd

from shared.problems import Catalog


def problem_labels(
    windows: pd.DataFrame,
    events: pd.DataFrame,
    version: str,
    catalog: Catalog,
    positions: Mapping[int, int],
) -> pd.DataFrame:
    """Etiqueta las ventanas de una sesión según los problemas activos.

    Args:
        windows: Ventanas de la sesión (``t_start``, ``t_end``).
        events: Eventos limpios de la sesión, con ``screen`` normalizada y ``task_id``.
        version: Versión de la sesión.
        catalog: Problemas sembrados.
        positions: Posición de cada tarea, por ``task_id``.

    Returns:
        ``label`` (0 o 1) y ``problems`` (números de los problemas presentes).
    """
    active = catalog.active(version)
    ordered = events[events["type"] != "camera_gap"].sort_values("t")
    times = ordered["t"].to_numpy(float)
    places = [
        (
            None if pd.isna(task) else positions.get(int(task)),
            screen if isinstance(screen, str) else None,
        )
        for task, screen in zip(ordered["task_id"], ordered["screen"], strict=True)
    ]
    labels, problems = [], []
    for low, high in zip(windows["t_start"], windows["t_end"], strict=True):
        first = int(times.searchsorted(low, "right")) - 1
        last = int(times.searchsorted(high, "left"))
        # El lugar en que estaba al empezar la ventana y los que visitó durante ella.
        visited = set(places[max(first, 0) : last]) if len(places) else set()
        present = tuple(
            problem.number
            for problem in active
            if any(
                task == problem.task and (not problem.screens or screen in problem.screens)
                for task, screen in visited
            )
        )
        labels.append(int(bool(present)))
        problems.append(present)
    return pd.DataFrame({"label": labels, "problems": problems}, index=windows.index)


def rule_flags(windows: pd.DataFrame, incidents: pd.DataFrame) -> pd.Series:
    """Si los detectores informaron algún incidente en cada ventana.

    Args:
        windows: Ventanas (``t_start``, ``t_end``).
        incidents: Incidentes de la sesión (``t``).

    Returns:
        1 si hubo al menos un incidente en la ventana, 0 si no.
    """
    times = incidents["t"].to_numpy(float) if len(incidents) else []
    return pd.Series(
        [
            int(any(low <= t < high for t in times))
            for low, high in zip(windows["t_start"], windows["t_end"], strict=True)
        ],
        index=windows.index,
        name="rules",
    )
