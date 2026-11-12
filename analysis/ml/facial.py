"""Movimientos faciales relativos a una línea base, sin inferir emociones.

No se generan imágenes ni etiquetas afectivas. La línea base debe estar marcada
en gaze_target; no se reconstruye con los primeros segundos de una sesión vieja.
Las ventanas con pose extrema o captura insuficiente quedan sin rasgos válidos.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

FEATURE_VERSION = "facial-1"
"""Versión de las definiciones de rasgos; debe cambiar al modificar umbrales."""

MOVEMENTS = {
    "brow_down": ("brow_down_left", "brow_down_right"),
    "brow_inner_up": ("brow_inner_up",),
    "mouth_press": ("mouth_press_left", "mouth_press_right"),
    "eye_squint": ("eye_squint_left", "eye_squint_right"),
    "eye_blink": ("eye_blink_left", "eye_blink_right"),
}
"""Grupos de movimientos del contrato, sin nombres de emociones."""


@dataclass(frozen=True)
class FacialSettings:
    """Umbrales iniciales para preparar rasgos; todavía pendientes del piloto.

    Attributes:
        window_ms: Ancho de la ventana de rasgos, entre 1 y 2 segundos.
        max_pose_deg: Giro o inclinación absoluta que invalida una muestra.
        min_valid_share: Fracción mínima de muestras útiles en la ventana.
        min_baseline_ms: Duración mínima cubierta por la captura neutra.
        min_baseline_samples: Cantidad mínima de muestras neutras útiles.
        blink_threshold: Intensidad desde la que se considera párpado cerrado.
        max_gap_ms: Separación máxima entre muestras para contar una transición.
    """

    window_ms: float = 2000
    max_pose_deg: float = 20
    min_valid_share: float = 0.8
    min_baseline_ms: float = 8000
    min_baseline_samples: int = 80
    blink_threshold: float = 0.45
    max_gap_ms: float = 250

    def __post_init__(self) -> None:
        """Rechaza tiempos, proporciones o límites fuera de rango."""
        values = vars(self)
        if any(not np.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("facial settings must be finite and positive")
        if not 1000 <= self.window_ms <= 2000:
            raise ValueError("facial window_ms must be between 1000 and 2000")
        if self.min_valid_share > 1 or self.blink_threshold >= 1:
            raise ValueError("facial proportions must be <= 1 and blink_threshold < 1")


@dataclass(frozen=True)
class NeutralBaseline:
    """Medianas de movimientos y tramo neutro realmente registrado.

    Attributes:
        t_start: Inicio del tramo marcado.
        t_end: Fin del tramo marcado.
        movements: Medianas por movimiento, en la escala original de MediaPipe.
        samples: Muestras útiles, con rostro y pose admisible.
    """

    t_start: float
    t_end: float
    movements: dict[str, float]
    samples: int


DEFAULT_SETTINGS = FacialSettings()
"""Definición inmutable de la primera versión de rasgos faciales."""


def _values(face: pd.DataFrame, settings: FacialSettings) -> pd.DataFrame:
    """Expande solo números del rostro y descarta pose y valores inválidos."""
    result = face[["t", "face_detected", "head_yaw", "head_pitch"]].copy()
    for name, keys in MOVEMENTS.items():

        def average(value: Any, keys: tuple[str, ...] = keys) -> float:
            if not isinstance(value, dict):
                return np.nan
            numbers = [value.get(key) for key in keys]
            if any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not np.isfinite(v)
                or not 0 <= v <= 1
                for v in numbers
            ):
                return np.nan
            return float(np.mean(numbers))

        result[name] = face["values"].map(average)
    result["usable"] = (
        result["face_detected"].fillna(False).astype(bool)
        & (result["head_yaw"].abs() <= settings.max_pose_deg)
        & (result["head_pitch"].abs() <= settings.max_pose_deg)
        & result[list(MOVEMENTS)].notna().all(axis=1)
    )
    return result.sort_values("t").drop_duplicates("t")


def neutral_baseline(
    face: pd.DataFrame, targets: pd.DataFrame, settings: FacialSettings = DEFAULT_SETTINGS
) -> NeutralBaseline:
    """Elige la última línea base neutra completa y con captura suficiente.

    Raises:
        ValueError: Si falta un tramo marcado o no tiene rostro y pose utilizables.
    """
    marked = targets[
        (targets["phase"] == "neutral_baseline") & (targets["calibration_type"] == "initial")
    ].sort_values("t", ascending=False)
    if marked.empty:
        raise ValueError("no usable marked neutral baseline; record a new initial calibration")
    expanded = _values(face, settings)
    for target in marked.itertuples():
        inside = expanded[(expanded["t"] >= target.t) & (expanded["t"] < target.t_end)]
        useful = inside[inside["usable"]]
        if len(useful) < settings.min_baseline_samples or inside.empty:
            continue
        if len(useful) / len(inside) < settings.min_valid_share:
            continue
        if useful["t"].max() - useful["t"].min() < settings.min_baseline_ms:
            continue
        if useful["t"].diff().max() > settings.max_gap_ms:
            continue
        return NeutralBaseline(
            float(target.t),
            float(target.t_end),
            useful[list(MOVEMENTS)].median().to_dict(),
            len(useful),
        )
    raise ValueError("no usable marked neutral baseline; record a new initial calibration")


def facial_windows(
    face: pd.DataFrame,
    baseline: NeutralBaseline,
    start: float,
    end: float,
    settings: FacialSettings = DEFAULT_SETTINGS,
) -> pd.DataFrame:
    """Rasgos por ventana posteriores a la línea base, con cobertura explícita.

    Cada movimiento es la media menos la mediana neutra de esa persona. La
    tasa de parpadeo cuenta cierres observados, sin cruzar huecos de captura.
    Ventanas parciales al final no se puntúan. No usa objetivos de mirada ni
    etiquetas de incidentes para fabricar rasgos.
    """
    if not np.isfinite(start) or not np.isfinite(end) or end < start:
        raise ValueError("invalid facial window interval")
    expanded = _values(face, settings)
    rows = []
    closed = expanded["eye_blink"] >= settings.blink_threshold
    closures = (
        closed
        & ~closed.shift(fill_value=True)
        & expanded["usable"]
        & expanded["usable"].shift(fill_value=False)
        & (expanded["t"].diff() <= settings.max_gap_ms)
    )
    for low in np.arange(max(start, baseline.t_end), end, settings.window_ms):
        high = min(low + settings.window_ms, end)
        inside = expanded[(expanded["t"] >= low) & (expanded["t"] < high)]
        useful = inside[inside["usable"]]
        coverage = len(useful) / len(inside) if len(inside) else 0.0
        valid = (
            high - low == settings.window_ms
            and len(useful) >= 2
            and coverage >= settings.min_valid_share
            and useful["t"].iloc[0] - low <= settings.max_gap_ms
            and high - useful["t"].iloc[-1] <= settings.max_gap_ms
            and useful["t"].diff().max() <= settings.max_gap_ms
        )
        row = {
            "t_start": float(low),
            "t_end": float(high),
            "valid": bool(valid),
            "samples": len(inside),
            "valid_share": coverage,
        }
        for name in MOVEMENTS:
            row[f"{name}_delta"] = (
                float(useful[name].mean() - baseline.movements[name]) if valid else np.nan
            )
        row["blink_rate_per_min"] = (
            float(
                closures[(expanded["t"] >= low) & (expanded["t"] < high)].sum()
                * 60000
                / settings.window_ms
            )
            if valid
            else np.nan
        )
        rows.append(row)
    return pd.DataFrame(
        rows,
        columns=[
            "t_start",
            "t_end",
            "valid",
            "samples",
            "valid_share",
            *(f"{name}_delta" for name in MOVEMENTS),
            "blink_rate_per_min",
        ],
    )
