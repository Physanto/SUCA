"""Acuerdo entre la detección automática y la codificación manual (P4).

El evaluador codifica a mano una muestra de tareas mirando la reproducción: si
la tarea se logró y en qué paso se desvió de la ruta. La plantilla CSV trae lo
automático y deja vacías las columnas manuales:

- ``manual_success``: ``1`` si se logró, ``0`` si no; vacío si no se codificó.
- ``manual_deviation_step``: el paso (desde 0) del primer desvío, ``none`` si
  no se desvió; vacío si no se codificó.
"""

from pathlib import Path
from typing import Any

import pandas as pd

from scripts.evaluation.repository import StudyResults
from scripts.evaluation.statistics import cohen_kappa

TEMPLATE_COLUMNS = (
    "session_id",
    "participant_id",
    "version",
    "task_position",
    "auto_success",
    "auto_deviation_step",
    "manual_success",
    "manual_deviation_step",
    "notes",
)
"""Columnas de la plantilla de codificación manual."""

NO_DEVIATION = "none"
"""Valor de ``*_deviation_step`` cuando la tarea no se desvió."""


def coding_template(results: StudyResults) -> pd.DataFrame:
    """Plantilla para codificar a mano las tareas del estudio.

    Args:
        results: Resultados del estudio.

    Returns:
        Una fila por sesión y tarea, con lo automático y las columnas manuales vacías.
    """
    participants = results.sessions.set_index("session_id")
    rows = [
        {
            "session_id": int(task.session_id),
            "participant_id": participants.at[task.session_id, "participant_id"],
            "version": participants.at[task.session_id, "version"],
            "task_position": int(task.position),
            "auto_success": int(bool(task.success)),
            "auto_deviation_step": _step(task.deviation_step),
            "manual_success": "",
            "manual_deviation_step": "",
            "notes": "",
        }
        for task in results.task_results.sort_values(["session_id", "position"]).itertuples()
    ]
    return pd.DataFrame(rows, columns=list(TEMPLATE_COLUMNS))


def read_coding(path: Path) -> pd.DataFrame:
    """Lee una plantilla codificada y valida sus columnas y valores.

    Args:
        path: Archivo CSV.

    Returns:
        Las filas, con ``manual_success`` como 0/1 o nulo y ``manual_deviation_step``
        como texto (paso o ``none``) o nulo.

    Raises:
        ValueError: Si faltan columnas o un valor manual no es válido.
    """
    coding = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in TEMPLATE_COLUMNS[:-1] if column not in coding.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    success = coding["manual_success"].str.strip()
    if not success.isin(["", "0", "1"]).all():
        raise ValueError(f"{path}: manual_success must be 1, 0 or empty")
    deviation = coding["manual_deviation_step"].str.strip().str.lower()
    valid = deviation.eq("") | deviation.eq(NO_DEVIATION) | deviation.str.fullmatch(r"\d+")
    if not valid.all():
        raise ValueError(f"{path}: manual_deviation_step must be a step, 'none' or empty")
    coding["manual_success"] = success.map({"": None, "0": 0, "1": 1})
    coding["manual_deviation_step"] = deviation.replace("", None)
    coding["auto_success"] = coding["auto_success"].astype(int)
    coding["auto_deviation_step"] = coding["auto_deviation_step"].str.strip().str.lower()
    return coding


def coding_agreement(coding: pd.DataFrame) -> dict[str, Any]:
    """Acuerdo de éxito y de punto de desvío entre lo automático y lo manual.

    Args:
        coding: Resultado de :func:`read_coding`.

    Returns:
        ``success`` y ``deviation`` con ``agreement``, ``kappa`` y ``n``; en
        ``deviation`` también ``within_one_step``: entre las tareas que ambos
        ven desviadas, la proporción con pasos a uno o menos de distancia.
    """
    success = coding.dropna(subset=["manual_success"])
    deviation = coding.dropna(subset=["manual_deviation_step"])
    both = deviation[
        (deviation["auto_deviation_step"] != NO_DEVIATION)
        & (deviation["manual_deviation_step"] != NO_DEVIATION)
    ]
    close = (
        both["auto_deviation_step"].astype(int) - both["manual_deviation_step"].astype(int)
    ).abs() <= 1
    return {
        "success": cohen_kappa(
            list(success["auto_success"]), list(success["manual_success"].astype(int))
        ),
        "deviation": cohen_kappa(
            list(deviation["auto_deviation_step"]), list(deviation["manual_deviation_step"])
        )
        | {
            "within_one_step": float(close.mean()) if len(both) else None,
            "both_deviated": len(both),
        },
    }


def _step(value: Any) -> str:
    """Paso de desvío como texto de la plantilla."""
    return NO_DEVIATION if value is None or pd.isna(value) else str(int(value))
