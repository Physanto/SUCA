"""Rasgos de cada ventana de 5 s: interacción, mirada y rostro.

Las ventanas cubren la sesión desde el fin de la calibración inicial; se
descartan las que se cruzan con cualquier otro procedimiento de la cámara
(comprobaciones de deriva, calibración final). Ningún rasgo usa los incidentes
de los detectores: así el modelo se puede comparar con las reglas sin que las
reglas estén dentro del modelo.

- **Interacción:** clics (y los que caen en elementos no interactivos),
  eventos, velocidad y aceleración del cursor, cambios de dirección, la pausa
  más larga, scroll, errores de validación, cambios de campos y de pantalla.
- **Mirada:** fracción de muestras válidas, dispersión, cambios de zona,
  fijaciones, su duración y la probabilidad de no mirar ningún elemento.
- **Rostro:** cada movimiento respecto de la línea base neutra de la persona y
  la tasa de parpadeo (``analysis/ml/facial.py``). Sin línea base, quedan vacíos.
"""

import math

import numpy as np
import pandas as pd

from analysis.loader import SessionData
from analysis.ml.facial import MOVEMENTS, FacialSettings, facial_windows, neutral_baseline

WINDOW_MS = 5000.0
"""Ancho de las ventanas del modelo, como en el plan del proyecto."""

INTERACTION_FEATURES = (
    "clicks",
    "non_interactive_clicks",
    "events",
    "cursor_px_per_s",
    "cursor_accel_px_per_s2",
    "direction_changes",
    "max_gap_s",
    "scroll_px",
    "validation_errors",
    "field_changes",
    "screen_changes",
)
"""Rasgos de interacción."""

GAZE_FEATURES = (
    "gaze_valid_share",
    "gaze_dispersion_px",
    "gaze_zone_changes",
    "fixations",
    "fixation_ms",
    "unassigned_p",
)
"""Rasgos de la mirada."""

FACE_FEATURES = (*(f"{name}_delta" for name in MOVEMENTS), "blink_rate_per_min")
"""Rasgos del rostro, relativos a la línea base neutra."""

FEATURE_GROUPS = {
    "interaction": INTERACTION_FEATURES,
    "gaze": GAZE_FEATURES,
    "face": FACE_FEATURES,
}
"""Rasgos por señal."""

_TURN_RAD = math.radians(90)
"""Giro del cursor desde el que cuenta un cambio de dirección."""


def session_windows(
    data: SessionData,
    targets: pd.DataFrame,
    fixations: pd.DataFrame,
    *,
    window_ms: float = WINDOW_MS,
) -> pd.DataFrame:
    """Ventanas de una sesión cerrada con sus rasgos.

    Args:
        data: Sesión cerrada, con eventos limpios.
        targets: Objetivos de los procedimientos de la cámara (``gaze_target``).
        fixations: Fijaciones atribuidas (``gaze_fixation``); vacía si no hay.
        window_ms: Ancho de las ventanas.

    Returns:
        Una fila por ventana con ``session_id``, ``participant_id``,
        ``version``, ``t_start``, ``t_end`` y los rasgos. Los de mirada o rostro
        quedan vacíos si la sesión no los tiene.

    Raises:
        ValueError: Si la sesión sigue abierta.
    """
    if data.session.ended_at is None:
        raise ValueError("model windows require a closed session")
    start = _after_initial_calibration(targets, data.session.started_at)
    end = float(data.session.ended_at)
    lows = np.arange(start, end - window_ms + 1e-9, window_ms)
    procedures = [
        (float(row.t), float(row.t_end))
        for row in targets.itertuples()
        if row.calibration_type != "initial"
    ]
    rows = []
    for low in lows:
        high = low + window_ms
        if any(begin < high and finish > low for begin, finish in procedures):
            continue
        rows.append(
            {"t_start": float(low), "t_end": float(high)}
            | _interaction(data.events, low, high)
            | _gaze(data.gaze, fixations, low, high)
        )
    windows = pd.DataFrame(
        rows, columns=["t_start", "t_end", *INTERACTION_FEATURES, *GAZE_FEATURES]
    )
    windows = _with_face(windows, data, targets, start, end, window_ms)
    return windows.assign(
        session_id=data.session.id,
        participant_id=data.session.participant_id,
        version=data.session.version,
    )


def _after_initial_calibration(targets: pd.DataFrame, started_at: float) -> float:
    """Fin de la calibración inicial, o el inicio de la sesión si no hubo."""
    initial = targets[targets["calibration_type"] == "initial"] if len(targets) else targets
    return max(float(started_at), float(initial["t_end"].max())) if len(initial) else started_at


def _interaction(events: pd.DataFrame, low: float, high: float) -> dict[str, float]:
    """Rasgos de interacción de una ventana."""
    seconds = (high - low) / 1000
    own = events[(events["t"] >= low) & (events["t"] < high) & (events["type"] != "camera_gap")]
    clicks = own[own["type"] == "click"]
    non_interactive = sum(
        isinstance(element, dict) and not element.get("interactive", True)
        for element in clicks["element"]
    )
    moves = own.loc[own["type"] == "mousemove", ["t", "x", "y"]].dropna().to_numpy(float)
    speed, accel, turns = 0.0, 0.0, 0
    if len(moves) > 1:
        steps = np.diff(moves[:, 1:], axis=0)
        gaps = np.maximum(np.diff(moves[:, 0]), 1.0) / 1000
        distances = np.hypot(steps[:, 0], steps[:, 1])
        speed = float(distances.sum() / seconds)
        speeds = distances / gaps
        accel = float(np.abs(np.diff(speeds) / gaps[1:]).mean()) if len(speeds) > 1 else 0.0
        moving = steps[distances > 0]
        if len(moving) > 1:
            angles = np.arctan2(moving[:, 1], moving[:, 0])
            change = np.abs(np.angle(np.exp(1j * np.diff(angles))))
            turns = int((change > _TURN_RAD).sum())
    times = np.concatenate([[low], own["t"].to_numpy(float), [high]])
    scrolls = own.loc[own["type"] == "scroll", "data"]
    offsets = [item.get("scroll_y") for item in scrolls if isinstance(item, dict)]
    offsets = [value for value in offsets if isinstance(value, int | float)]
    return {
        "clicks": float(len(clicks)),
        "non_interactive_clicks": float(non_interactive),
        "events": float(len(own)),
        "cursor_px_per_s": speed,
        "cursor_accel_px_per_s2": accel,
        "direction_changes": float(turns),
        "max_gap_s": float(np.diff(times).max() / 1000),
        "scroll_px": float(np.abs(np.diff(offsets)).sum()) if len(offsets) > 1 else 0.0,
        "validation_errors": float((own["type"] == "validation_error").sum()),
        "field_changes": float((own["type"] == "field_change").sum()),
        "screen_changes": float((own["type"] == "screen_change").sum()),
    }


def _gaze(gaze: pd.DataFrame, fixations: pd.DataFrame, low: float, high: float) -> dict[str, float]:
    """Rasgos de la mirada de una ventana; vacíos si la sesión no tiene mirada."""
    if gaze.empty:
        return dict.fromkeys(GAZE_FEATURES, np.nan)
    own = gaze[(gaze["t"] >= low) & (gaze["t"] < high)]
    if own.empty:
        return dict.fromkeys(GAZE_FEATURES, np.nan)
    valid = own[own["valid"].astype(bool) & own["x"].notna() & own["y"].notna()]
    dispersion = (
        float(np.hypot(valid["x"].std(ddof=0), valid["y"].std(ddof=0))) if len(valid) > 1 else 0.0
    )
    zones = valid["zone"].dropna() if "zone" in valid else pd.Series(dtype=object)
    inside = (
        fixations[(fixations["t_start"] < high) & (fixations["t_end"] > low)]
        if len(fixations)
        else fixations
    )
    durations = (
        (inside["t_end"].clip(upper=high) - inside["t_start"].clip(lower=low))
        if len(inside)
        else pd.Series(dtype=float)
    )
    return {
        "gaze_valid_share": float(len(valid) / len(own)),
        "gaze_dispersion_px": dispersion,
        "gaze_zone_changes": float((zones != zones.shift()).sum() - 1) if len(zones) else 0.0,
        "fixations": float(len(inside)),
        "fixation_ms": float(durations.sum()),
        "unassigned_p": (
            float(np.average(inside["unassigned_p"], weights=durations))
            if durations.sum() > 0
            else 0.0
        ),
    }


def _with_face(
    windows: pd.DataFrame,
    data: SessionData,
    targets: pd.DataFrame,
    start: float,
    end: float,
    window_ms: float,
) -> pd.DataFrame:
    """Agrega los rasgos del rostro; vacíos si no hay una línea base neutra utilizable."""
    result = windows.copy()
    for name in FACE_FEATURES:
        result[name] = np.nan
    if result.empty or data.face.empty or targets.empty:
        return result
    settings = FacialSettings(window_ms=window_ms)
    try:
        baseline = neutral_baseline(data.face, targets, settings)
    except ValueError:
        return result
    face = facial_windows(data.face, baseline, start, end, settings)
    face = face[face["valid"]].set_index("t_start")
    for index, low in result["t_start"].items():
        if low in face.index:
            for name in FACE_FEATURES:
                result.at[index, name] = face.at[low, name]
    return result
