"""Evidencia de mirada antes de incidentes, usando exclusivamente p_gaze.

Conserva cada referencia por separado para no elegir la que más favorece una
hipótesis. Ausencia de atribución es un dato faltante, no probabilidad cero.
"""

import pandas as pd

from analysis.gaze.attention import probability_seen
from analysis.reference import next_reference_step
from dashboard.heatmap import screen_key

LOOKBACK_MS = 5000
"""Tramo anterior al incidente que se consulta."""


def before_incidents(
    incidents: pd.DataFrame,
    events: pd.DataFrame,
    references: pd.DataFrame,
    fixations: pd.DataFrame,
    candidates: pd.DataFrame,
    tasks: pd.DataFrame,
) -> pd.DataFrame:
    """Probabilidad de haber mirado el siguiente elemento de cada referencia.

    Args:
        incidents: Incidentes de una sesión.
        events: Eventos de esa sesión, sin filtrar por tiempo.
        references: Referencias del estudio; solo se usan las confirmadas.
        fixations: Fijaciones de la sesión con pantalla.
        candidates: Atribuciones de la sesión (p_attention se ignora).
        tasks: Tramos de tarea de la sesión para no mezclar intentos.

    Returns:
        Una fila por incidente y referencia, o una fila sin evidencia cuando
        falta una referencia o captura. Incluye la razón del dato ausente.
    """
    rows = []
    for incident in incidents.itertuples():
        refs = references[
            (references["task_id"] == incident.task_id) & (references["status"] == "confirmed")
        ]
        base = {"t": incident.t, "type": incident.type, "task_id": incident.task_id}
        if refs.empty:
            rows.append(
                {
                    **base,
                    "reference_id": None,
                    "selector": None,
                    "p_seen": None,
                    "fixations": 0,
                    "reason": "Sin referencia confirmada",
                }
            )
            continue
        periods = tasks[
            (tasks["task_id"] == incident.task_id)
            & (tasks["t_start"] <= incident.t)
            & (tasks["t_end"] >= incident.t)
        ]
        if periods.empty:
            rows.append(
                {
                    **base,
                    "reference_id": None,
                    "selector": None,
                    "p_seen": None,
                    "fixations": 0,
                    "reason": "Sin tramo de tarea en ese momento",
                }
            )
            continue
        beginning = float(periods["t_start"].max())
        history = events[
            (events["task_id"] == incident.task_id)
            & (events["t"] >= beginning)
            & (events["t"] < incident.t)
        ]
        low = max(beginning, incident.t - LOOKBACK_MS)
        for reference in refs.itertuples():
            position = next_reference_step(history, reference.steps)
            next_step = reference.steps[position] if position < len(reference.steps) else None
            element = next_step.get("element") if next_step else None
            selector = element.get("selector") if element else None
            row = {
                **base,
                "reference_id": reference.reference_id,
                "selector": selector,
                "p_seen": None,
                "fixations": 0,
                "reason": "",
            }
            if selector is None:
                row["reason"] = "Ruta terminada o paso siguiente sin elemento"
                rows.append(row)
                continue
            expected_screen = screen_key(next_step["screen"]["url"])
            inside = (
                fixations[
                    (fixations["t_end"] >= low)
                    & (fixations["t_end"] <= incident.t)
                    & (fixations["t_start"] >= beginning)
                    & (fixations["screen"].fillna("").map(screen_key) == expected_screen)
                ]
                if not fixations.empty
                else fixations
            )
            row["fixations"] = len(inside)
            if inside.empty or candidates.empty:
                row["reason"] = "Sin fijaciones atribuidas previas en esa pantalla"
            else:
                # p_attention incorpora clics: usarlo aquí inflaría la comparación P5.
                row["p_seen"] = probability_seen(
                    candidates, inside, selector, low, incident.t, attention=False
                )
            rows.append(row)
    return pd.DataFrame(
        rows,
        columns=[
            "t",
            "type",
            "task_id",
            "reference_id",
            "selector",
            "p_seen",
            "fixations",
            "reason",
        ],
    )
