"""Muestras de mirada con objetivo conocido.

Junta cada cuadro (``gaze_feature``) con el punto que la persona debía mirar en
ese momento (``gaze_target``): los puntos fijos de la calibración, el recorrido
del punto en movimiento, el punto central mientras se mueve la cabeza, los
puntos de validación y los de las comprobaciones de deriva. Con eso se mide el
error de la mirada y se vuelve a ajustar el modelo.

Funciones puras sobre DataFrames: se prueban sin la base.
"""

import numpy as np
import pandas as pd

from analysis.gaze.model import FEATURE_COLUMNS

INITIAL = "initial"
"""Tipo de la calibración que entrena (``calibration_type``)."""

PURSUIT = "pursuit"
"""Fase del punto en movimiento (``gaze_target_phase``)."""

TRAINING_PHASES = ("points", "pursuit", "head")
"""Fases que entrenan el modelo en la calibración inicial."""

PURSUIT_CHUNKS = 4
"""Tramos en que se parte el recorrido del punto en movimiento para la validación cruzada."""

EVENT_GAP_MS = 60_000
"""Objetivos del mismo tipo separados por más que esto pertenecen a procedimientos distintos."""

SAMPLE_COLUMNS = (
    "t",
    "frame",
    "target_x",
    "target_y",
    "group",
    "calibration_type",
    "phase",
    "event",
    "viewport_width",
    "viewport_height",
)
"""Columnas de las muestras con objetivo."""


def geometric_features(frames: pd.DataFrame) -> pd.DataFrame:
    """Características geométricas de cada cuadro, como las arma la extensión.

    Promedia los dos ojos (``h``, ``v`` y apertura); si falta uno, usa el otro.

    Args:
        frames: Filas de ``gaze_feature``.

    Returns:
        DataFrame con las columnas de ``FEATURE_COLUMNS`` y el mismo índice. Un
        cuadro sin rostro o sin alguna medida tiene ``NaN``.
    """

    def both(column: str) -> pd.Series:
        pair = frames[[f"left_{column}", f"right_{column}"]].astype(float)
        return pair.mean(axis=1, skipna=True)

    return pd.DataFrame(
        {
            "yaw": frames["head_yaw"].astype(float),
            "pitch": frames["head_pitch"].astype(float),
            "distance": frames["distance_cm"].astype(float),
            "eye_u": frames["eye_u"].astype(float),
            "eye_v": frames["eye_v"].astype(float),
            "aspect": frames["aspect"].astype(float),
            "h": both("h"),
            "v": both("v"),
            "open": both("open"),
        },
        index=frames.index,
    )[list(FEATURE_COLUMNS)]


def usable(frames: pd.DataFrame, blink_threshold: float) -> pd.Series:
    """Cuadros con rostro, todas las medidas y ojos abiertos.

    Args:
        frames: Filas de ``gaze_feature``.
        blink_threshold: Parpadeo desde el que un cuadro se descarta.

    Returns:
        Máscara booleana con el índice de ``frames``.
    """
    complete = geometric_features(frames).notna().all(axis=1)
    blink = frames["blink"].astype(float)
    open_eyes = blink.isna() | (blink < blink_threshold)
    return frames["face_detected"].astype(bool) & complete & open_eyes


def events(targets: pd.DataFrame) -> pd.Series:
    """Numera los procedimientos: objetivos seguidos del mismo tipo forman uno.

    Args:
        targets: Filas de ``gaze_target`` (``t``, ``t_end``, ``calibration_type``).

    Returns:
        Número de procedimiento de cada objetivo, desde 0, en orden de tiempo.
    """
    ordered = targets.sort_values("t")
    numbers: dict[int, int] = {}
    current = -1
    last_type = None
    last_end = -np.inf
    for index, row in ordered.iterrows():
        if row["calibration_type"] != last_type or row["t"] - last_end > EVENT_GAP_MS:
            current += 1
        numbers[index] = current
        last_type = row["calibration_type"]
        last_end = row["t_end"]
    return pd.Series(numbers, dtype="int64").reindex(targets.index)


def _path_at(points: list[dict], t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Posición de un recorrido en unos momentos, interpolando; fuera, el extremo."""
    path = sorted(points, key=lambda point: point["t"])
    times = np.array([point["t"] for point in path], dtype=float)
    return (
        np.interp(t, times, np.array([point["x"] for point in path], dtype=float)),
        np.interp(t, times, np.array([point["y"] for point in path], dtype=float)),
    )


def target_samples(
    frames: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    blink_threshold: float,
    pursuit_skip_ms: float,
    delay_ms: float = 0.0,
) -> pd.DataFrame:
    """Cada cuadro utilizable con el punto que debía mirarse en ese momento.

    Args:
        frames: Filas de ``gaze_feature``, con su índice.
        targets: Filas de ``gaze_target`` (``points`` ya es una lista).
        blink_threshold: Parpadeo desde el que un cuadro se descarta.
        pursuit_skip_ms: Tramo inicial del punto en movimiento que se descarta
            (los ojos tardan en engancharse).
        delay_ms: Retraso de la cámara: un cuadro con marca ``t`` muestra el ojo
            de ``t − delay_ms``, que en el seguimiento miraba el punto de ese momento.

    Returns:
        Una fila por cuadro y objetivo, con las columnas de ``SAMPLE_COLUMNS``.
        ``frame`` es el índice del cuadro en ``frames``; ``group`` identifica el
        objetivo (el recorrido del punto en movimiento, en ``PURSUIT_CHUNKS`` tramos).
    """
    if frames.empty or targets.empty:
        return pd.DataFrame(columns=list(SAMPLE_COLUMNS))
    ok = usable(frames, blink_threshold)
    times = frames["t"].to_numpy(float)
    numbers = events(targets)
    parts = []
    for index, target in targets.iterrows():
        # La línea base facial no valida ni entrena el estimador de mirada.
        if target["phase"] == "neutral_baseline":
            continue
        start = float(target["t"]) + (pursuit_skip_ms if target["phase"] == PURSUIT else 0)
        inside = (times >= start) & (times <= float(target["t_end"])) & ok.to_numpy()
        if not inside.any():
            continue
        t = times[inside]
        kind = f"{target['calibration_type']}:{target['phase']}:{target['group']}"
        key = f"{int(numbers[index])}:{kind}"
        if target["phase"] == PURSUIT:
            x, y = _path_at(target["points"], t - delay_ms)
            span = max(t[-1] - t[0], 1.0)
            chunk = np.minimum(PURSUIT_CHUNKS - 1, ((t - t[0]) / span * PURSUIT_CHUNKS).astype(int))
            group = [f"{key}:{c}" for c in chunk]
        else:
            first = target["points"][0]
            x = np.full(t.size, float(first["x"]))
            y = np.full(t.size, float(first["y"]))
            group = [key] * t.size
        parts.append(
            pd.DataFrame(
                {
                    "t": t,
                    "frame": frames.index[inside],
                    "target_x": x,
                    "target_y": y,
                    "group": group,
                    "calibration_type": target["calibration_type"],
                    "phase": target["phase"],
                    "event": int(numbers[index]),
                    "viewport_width": float(target["viewport_width"]),
                    "viewport_height": float(target["viewport_height"]),
                }
            )
        )
    if not parts:
        return pd.DataFrame(columns=list(SAMPLE_COLUMNS))
    return pd.concat(parts, ignore_index=True)[list(SAMPLE_COLUMNS)]


def px_to_deg(error_px: np.ndarray, distance_cm: np.ndarray, css_px_per_cm: float) -> np.ndarray:
    """Pasa errores en píxeles CSS a grados de ángulo visual a cada distancia.

    Args:
        error_px: Errores en píxeles.
        distance_cm: Distancia a la pantalla de cada muestra, en centímetros.
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.

    Returns:
        Errores en grados.
    """
    return np.degrees(
        np.arctan(np.asarray(error_px, float) / css_px_per_cm / np.asarray(distance_cm, float))
    )


def camera_delay(calibrations: pd.DataFrame) -> float:
    """Retraso de la cámara medido en la última calibración inicial que lo trae.

    Args:
        calibrations: Filas de ``calibration`` (``t``, ``type``, ``camera_delay_ms``).

    Returns:
        Retraso en milisegundos; 0 si ninguna calibración lo midió.
    """
    if calibrations.empty or "camera_delay_ms" not in calibrations:
        return 0.0
    measured = calibrations[
        (calibrations["type"] == INITIAL) & calibrations["camera_delay_ms"].notna()
    ]
    return float(measured.sort_values("t")["camera_delay_ms"].iloc[-1]) if len(measured) else 0.0
