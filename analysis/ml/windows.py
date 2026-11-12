"""Ventanas multimodales con etiquetas débiles de incidentes y tareas fallidas.

Las etiquetas sirven para preparar el experimento; no son una evaluación
independiente de fricción. Ninguna etiqueta se usa como característica.
"""

import numpy as np
import pandas as pd

from analysis.loader import SessionData
from analysis.ml.facial import DEFAULT_SETTINGS, FacialSettings, facial_windows, neutral_baseline

INTERACTION_FEATURES = ("clicks_per_s", "events_per_s", "cursor_px_per_s")
GAZE_FEATURES = ("gaze_valid_share", "gaze_fixation_ms", "gaze_unassigned_p")
FACIAL_FEATURES = (
    "brow_down_delta",
    "brow_inner_up_delta",
    "mouth_press_delta",
    "eye_squint_delta",
    "eye_blink_delta",
    "blink_rate_per_min",
)
"""Grupos comparables de características, sin etiquetas ni identidad de la persona."""


def build_windows(
    data: SessionData,
    targets: pd.DataFrame,
    fixations: pd.DataFrame,
    incidents: pd.DataFrame,
    task_results: pd.DataFrame,
    settings: FacialSettings = DEFAULT_SETTINGS,
) -> pd.DataFrame:
    """Construye ventanas después de una línea base válida y fuera de calibraciones.

    Args:
        data: Sesión cerrada con eventos, mirada, rostro y tareas.
        targets: Objetivos del procedimiento con t, t_end y phase.
        fixations: Fijaciones atribuidas, con unassigned_p.
        incidents: Incidentes ya calculados, usados solo para etiquetar.
        task_results: Resultados ya calculados; se etiqueta la ventana del fin fallido.
        settings: Definición versionada de ventanas y calidad facial.

    Returns:
        Una ventana por fila con rasgos, calidad y etiqueta débil (0/1).
    """
    if data.session.ended_at is None:
        raise ValueError("facial windows require a closed session")
    baseline = neutral_baseline(data.face, targets, settings)
    result = facial_windows(
        data.face, baseline, data.session.started_at, data.session.ended_at, settings
    )
    for feature in (*INTERACTION_FEATURES, *GAZE_FEATURES, "label"):
        result[feature] = np.nan
    failures = set(task_results.loc[~task_results["success"].astype(bool), "task_id"])
    failed_ends = data.tasks.loc[data.tasks["task_id"].isin(failures), "t_end"]
    for index, row in result.iterrows():
        low, high = row["t_start"], row["t_end"]
        procedure = ((targets["t"] < high) & (targets["t_end"] > low)).any()
        result.loc[index, "valid"] = bool(row["valid"] and not procedure)
        own = data.events[(data.events["t"] >= low) & (data.events["t"] < high)]
        seconds = (high - low) / 1000
        result.loc[index, "clicks_per_s"] = (own["type"] == "click").sum() / seconds
        # camera_gap describe la adquisición, no el comportamiento del participante.
        result.loc[index, "events_per_s"] = (own["type"] != "camera_gap").sum() / seconds
        cursor = own.loc[own["type"] == "mousemove", ["x", "y"]].dropna().to_numpy(float)
        result.loc[index, "cursor_px_per_s"] = (
            float(np.hypot(*np.diff(cursor, axis=0).T).sum()) / seconds if len(cursor) > 1 else 0
        )
        gaze = data.gaze[(data.gaze["t"] >= low) & (data.gaze["t"] < high)]
        result.loc[index, "gaze_valid_share"] = gaze["valid"].astype(float).mean()
        inside = fixations[(fixations["t_start"] < high) & (fixations["t_end"] > low)]
        durations = inside["t_end"].clip(upper=high) - inside["t_start"].clip(lower=low)
        result.loc[index, "gaze_fixation_ms"] = float(durations.sum())
        result.loc[index, "gaze_unassigned_p"] = (
            float(np.average(inside["unassigned_p"], weights=durations))
            if durations.sum() > 0
            else (0.0 if len(gaze) else np.nan)
        )
        has_incident = ((incidents["t"] >= low) & (incidents["t"] < high)).any()
        has_failure = ((failed_ends >= low) & (failed_ends < high)).any()
        result.loc[index, "label"] = int(has_incident or has_failure)
    result["session_id"] = data.session.id
    result["participant_id"] = data.session.participant_id
    return result
