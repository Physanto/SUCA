"""Movimientos alrededor de incidentes frente a ventanas de control de la misma persona."""

import numpy as np
import pandas as pd

from analysis.ml.facial import MOVEMENTS, FacialSettings, facial_windows, neutral_baseline

MOVEMENT_LABELS = {
    "brow_down": "Descenso de cejas",
    "brow_inner_up": "Elevación interna de cejas",
    "mouth_press": "Presión de labios",
    "eye_squint": "Entrecerrar los ojos",
    "eye_blink": "Cierre de párpados",
}
"""Nombres observables; no representan estados emocionales."""


def incident_comparison(
    face: pd.DataFrame,
    targets: pd.DataFrame,
    incidents: pd.DataFrame,
    start: float,
    end: float,
) -> pd.DataFrame:
    """Compara ventanas de ±2 s del incidente con control a más de 5 s de todos ellos.

    Excluye calibraciones y muestras sin calidad. La diferencia se expresa en
    la escala de MediaPipe respecto de la línea base de la misma persona.
    """
    settings = FacialSettings()
    baseline = neutral_baseline(face, targets, settings)
    windows = facial_windows(face, baseline, start, end, settings)
    windows = windows[windows["valid"]].copy()
    if windows.empty:
        return pd.DataFrame()
    centers = (windows["t_start"] + windows["t_end"]) / 2
    times = incidents["t"].to_numpy(float)
    distance = (
        np.min(np.abs(centers.to_numpy()[:, None] - times[None, :]), axis=1)
        if len(times)
        else np.full(len(windows), np.inf)
    )
    procedure = np.zeros(len(windows), dtype=bool)
    for target in targets.itertuples():
        procedure |= (windows["t_start"] < target.t_end) & (windows["t_end"] > target.t)
    nearby = windows[(distance <= 2000) & ~procedure]
    control = windows[(distance > 5000) & ~procedure]
    return pd.DataFrame(
        [
            {
                "Movimiento": MOVEMENT_LABELS[name],
                "Junto al incidente": nearby[f"{name}_delta"].mean(),
                "Control": control[f"{name}_delta"].mean(),
                "Ventanas junto al incidente": len(nearby),
                "Ventanas de control": len(control),
            }
            for name in MOVEMENTS
        ]
    )
