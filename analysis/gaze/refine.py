"""Reprocesamiento de la mirada al cerrar la sesión.

En vivo, la mirada solo conoce la calibración inicial y lo ocurrido hasta ese
momento. Al cerrar la sesión se conoce todo: las validaciones, las
comprobaciones de deriva y la validación final. Con eso:

1. **Reajuste.** El estimador geométrico se ajusta de nuevo
   (``analysis/gaze/model.py``) de dos formas: solo con la calibración inicial y
   con todos los puntos conocidos. Se usa la que menos se equivoca, y solo
   si se equivoca menos que la mirada en vivo; si no, se conserva la de vivo.
2. **Deriva en el tiempo.** El error de cada procedimiento de control
   (validación, vuelta del teclado, comprobación de deriva) da un
   desplazamiento en su momento; en el momento de la calibración vale 0, y
   entre medias se interpola. Solo se aplica si, medido de forma honesta,
   mejora el error.
3. **Suavizado de Kalman en dos pasadas** (Rauch-Tung-Striebel), dentro de cada
   tramo en que la persona mira la pantalla y sin cruzar un salto de la mirada:
   usa también los cuadros siguientes, algo imposible en vivo.
4. **Fijaciones** con el algoritmo I-DT.
5. **Zona y elemento** de cada punto con la disposición registrada (``layout.py``).

**Medición honesta.** El error refinado de cada punto de control se calcula
con un modelo ajustado sin ese punto y una corrección de deriva interpolada sin
su procedimiento. Así el error que se informa no se mide con los mismos datos
que lo corrigieron.

Si no hay calibración inicial con sus características, se usa la mirada en
vivo (``raw_x``, ``raw_y``) y solo se suaviza, se agrupa en fijaciones y se
asignan zonas.

Funciones puras sobre DataFrames; el orquestador (``analysis/run.py``) carga y
guarda.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis import columns
from analysis.gaze import GazeSettings
from analysis.gaze.layout import assign
from analysis.gaze.model import (
    MIN_GROUPS,
    FitResult,
    GeometricModel,
    fit_geometric,
    fit_with_lambda,
)
from analysis.gaze.samples import (
    INITIAL,
    TRAINING_PHASES,
    camera_delay,
    geometric_features,
    px_to_deg,
    target_samples,
    usable,
)
from analysis.loader import GazeInputs

LOOKING = ("on_screen", "low_confidence")
"""Estados de ``gaze_state`` en que la persona mira la pantalla."""

GEOMETRIC = "geometric"
"""Método del refinado: el estimador geométrico reajustado."""

LIVE = "live"
"""Método del refinado sin calibración utilizable: la mirada en vivo, solo suavizada."""

CALIBRATION_SCOPE = "calibration"
"""Modelo entrenado solo con la calibración inicial."""

ALL_TARGETS_SCOPE = "all_targets"
"""Modelo entrenado con todos los puntos conocidos de la sesión."""

MAX_GAP_MS = 100.0
"""Un hueco mayor entre cuadros corta el tramo de suavizado."""

DEFAULT_NOISE_PX = 25.0
"""Ruido de medición si no hay puntos fijos para estimarlo."""


@dataclass(frozen=True)
class GazeRefinement:
    """Mirada reprocesada de una sesión.

    Attributes:
        samples: Una fila por cuadro (tabla ``gaze_refined``).
        quality: Una fila con el método y el error en vivo y refinado (tabla ``gaze_quality``).
    """

    samples: pd.DataFrame
    quality: pd.DataFrame


def refine(inputs: GazeInputs, settings: GazeSettings) -> GazeRefinement:
    """Reprocesa la mirada de una sesión.

    Args:
        inputs: Cuadros, objetivos, calibraciones y disposiciones de la sesión.
        settings: Ajustes de la mirada.

    Returns:
        Mirada refinada y su calidad. Sin cuadros, las dos tablas vacías.
    """
    frames = inputs.features.reset_index(drop=True)
    if frames.empty:
        return GazeRefinement(columns.empty("gaze_refined"), columns.empty("gaze_quality"))
    features = geometric_features(frames)
    ok = usable(frames, settings.blink_threshold).to_numpy()
    delay = camera_delay(inputs.calibrations)
    samples = target_samples(
        frames,
        inputs.targets,
        blink_threshold=settings.blink_threshold,
        pursuit_skip_ms=settings.params.pursuit_skip_ms,
        delay_ms=delay,
    )
    distance = frames["distance_cm"].astype(float).fillna(settings.viewing_distance_cm).to_numpy()
    estimate = _estimate(frames, features, ok, samples, settings)
    x, y = estimate.x, estimate.y
    looking = frames["state"].isin(LOOKING).to_numpy() & np.isfinite(x) & np.isfinite(y)
    px_per_deg = settings.css_px_per_cm * distance * np.tan(np.radians(1.0))
    segments = _segments(frames["t"].to_numpy(float), x, y, looking, px_per_deg, settings)
    sx, sy = _smooth(
        frames["t"].to_numpy(float), x, y, segments, px_per_deg, estimate.noise_px, settings
    )
    fixation = _fixations(frames["t"].to_numpy(float), sx, sy, segments, px_per_deg, settings)
    width = frames["viewport_width"].to_numpy(float)
    height = frames["viewport_height"].to_numpy(float)
    inside = looking & (sx >= 0) & (sy >= 0) & (sx < width) & (sy < height)
    points = pd.DataFrame(
        {
            "t": frames["t"],
            "x": np.where(inside, sx, np.nan),
            "y": np.where(inside, sy, np.nan),
            "scroll_x": frames["scroll_x"],
            "scroll_y": frames["scroll_y"],
            "viewport_width": width,
            "viewport_height": height,
        }
    )
    places = assign(points, inputs.layouts)
    refined = columns.frame(
        "gaze_refined",
        [
            {
                "t": float(frames["t"].iloc[i]),
                "x": float(sx[i]) if looking[i] else None,
                "y": float(sy[i]) if looking[i] else None,
                "scroll_x": float(frames["scroll_x"].iloc[i]),
                "scroll_y": float(frames["scroll_y"].iloc[i]),
                "state": frames["state"].iloc[i],
                "confidence": float(frames["confidence"].iloc[i]),
                "valid": bool(inside[i]),
                "zone": places["zone"].iloc[i],
                "element_selector": places["element_selector"].iloc[i],
                "fixation": int(fixation[i]) if fixation[i] >= 0 else None,
            }
            for i in range(len(frames))
        ],
    )
    quality = columns.frame(
        "gaze_quality",
        [
            {
                "method": estimate.method,
                "fit_scope": estimate.fit_scope,
                "frames": len(frames),
                "check_samples": estimate.check_samples,
                "camera_delay_ms": delay,
                "live_error_deg": estimate.live_error_deg,
                "refined_error_deg": estimate.refined_error_deg,
                "drift_corrected": estimate.drift_corrected,
                "residual_lambda": estimate.lam,
                "noise_px": estimate.noise_px,
                "fixations": int(fixation.max() + 1) if (fixation >= 0).any() else 0,
            }
        ],
    )
    return GazeRefinement(refined, quality)


@dataclass(frozen=True)
class _Estimate:
    """Punto de cada cuadro antes del suavizado, y cómo se obtuvo."""

    x: np.ndarray
    y: np.ndarray
    method: str
    fit_scope: str | None
    check_samples: int
    live_error_deg: float | None
    refined_error_deg: float | None
    drift_corrected: bool
    lam: float | None
    noise_px: float


def _mean_or_none(values: np.ndarray) -> float | None:
    """Media de los valores finitos, o ``None``."""
    finite = values[np.isfinite(values)]
    return float(finite.mean()) if finite.size else None


def _estimate(
    frames: pd.DataFrame,
    features: pd.DataFrame,
    ok: np.ndarray,
    samples: pd.DataFrame,
    settings: GazeSettings,
) -> _Estimate:
    """Reajusta el modelo, mide su error de forma honesta y decide la corrección de deriva.

    Compara dos modelos y, para cada uno, con y sin corrección de deriva, y se queda
    con la combinación de menor error honesto en los puntos de control. Si ninguna
    mejora el error de la mirada en vivo, se queda con la mirada en vivo:

    - ``calibration``: entrenado solo con la calibración inicial. Los controles no
      lo entrenan, así que su error es honesto sin más.
    - ``all_targets``: entrenado con todos los puntos conocidos; cada control se
      predice con un modelo ajustado sin él. Aprovecha las posturas de los controles,
      pero puede confundir la deriva con un cambio de postura.

    La deriva se ancla en 0 en el momento de la calibración (el modelo se ajustó a
    ella) y, en cada procedimiento de control, se interpola sin ese procedimiento.
    """
    live_x = frames["raw_x"].astype(float).to_numpy()
    live_y = frames["raw_y"].astype(float).to_numpy()
    distance = frames["distance_cm"].astype(float).fillna(settings.viewing_distance_cm).to_numpy()
    checks = samples[~samples["phase"].isin(TRAINING_PHASES)] if len(samples) else samples
    rows = checks["frame"].to_numpy(int) if len(checks) else np.array([], dtype=int)
    target_x = checks["target_x"].to_numpy(float) if len(checks) else np.array([])
    target_y = checks["target_y"].to_numpy(float) if len(checks) else np.array([])

    def error_deg(px: np.ndarray, py: np.ndarray) -> float | None:
        """Error medio en grados de unas predicciones de los puntos de control."""
        errors = np.hypot(px - target_x, py - target_y)
        return _mean_or_none(px_to_deg(errors, distance[rows], settings.css_px_per_cm))

    live_error = error_deg(live_x[rows], live_y[rows]) if len(checks) else None
    live = _Estimate(
        x=live_x,
        y=live_y,
        method=LIVE,
        fit_scope=None,
        check_samples=len(checks),
        live_error_deg=live_error,
        refined_error_deg=live_error,
        drift_corrected=False,
        lam=None,
        noise_px=_noise(checks, live_x[rows], live_y[rows]) if len(checks) else DEFAULT_NOISE_PX,
    )
    training = (
        samples[samples["phase"].isin(TRAINING_PHASES) & (samples["calibration_type"] == INITIAL)]
        if len(samples)
        else samples
    )
    if training.empty or training["group"].nunique() < MIN_GROUPS:
        return live
    # Solo la última calibración inicial: si se repitió, las anteriores ya no valen.
    training = training[training["event"] == training["event"].max()]
    viewport_width = float(training["viewport_width"].iloc[0])
    anchor = float(training["t"].median())

    def fit(chosen: pd.DataFrame) -> FitResult:
        return fit_geometric(
            features.loc[chosen["frame"]],
            chosen["target_x"],
            chosen["target_y"],
            chosen["group"],
            viewport_width=viewport_width,
            css_px_per_cm=settings.css_px_per_cm,
        )

    candidates: dict[str, tuple[GeometricModel, float | None, np.ndarray, np.ndarray]] = {}
    calibration = fit(training)
    if calibration.model is not None:
        px, py = (
            calibration.model.predict(features.loc[rows]) if len(checks) else (np.array([]),) * 2
        )
        candidates[CALIBRATION_SCOPE] = (calibration.model, calibration.lam, px, py)
    if len(checks) and calibration.model is not None:
        everything = pd.concat([training, checks], ignore_index=True)
        full = fit(everything)
        if full.model is not None:
            loo_x = np.full(len(checks), np.nan)
            loo_y = np.full(len(checks), np.nan)
            for group in checks["group"].unique():
                keep = everything["group"] != group
                held = (checks["group"] == group).to_numpy()
                fold = fit_with_lambda(
                    features.loc[everything.loc[keep, "frame"]],
                    everything.loc[keep, "target_x"],
                    everything.loc[keep, "target_y"],
                    everything.loc[keep, "group"],
                    viewport_width=viewport_width,
                    css_px_per_cm=settings.css_px_per_cm,
                    lam=full.lam,
                    initial=full.model.params,
                )
                loo_x[held], loo_y[held] = fold.predict(features.loc[checks.loc[held, "frame"]])
            candidates[ALL_TARGETS_SCOPE] = (full.model, full.lam, loo_x, loo_y)
    if not candidates:
        return live

    # Para cada modelo, sin y con deriva; gana el menor error honesto.
    best = None
    for scope, (model, lam, px, py) in candidates.items():
        options = [(error_deg(px, py), False, None)]
        if len(checks):
            table = _event_offsets(checks, target_x - px, target_y - py)
            if len(table) >= 1:
                ox, oy = _leave_one_event_out(checks, table, anchor)
                options.append((error_deg(px + ox, py + oy), True, table))
        for error, drift, table in options:
            score = np.inf if error is None else error
            if best is None or score < best[0]:
                best = (score, scope, model, lam, px, py, drift, table, error)
    _, scope, model, lam, px, py, drift, table, error = best
    # El reajuste solo vale si mejora lo que ya se midió en vivo; si no, reemplazaría
    # una mirada mejor por una peor (con otra cámara o persona el modelo geométrico
    # puede ajustar peor que el estimador que ganó en vivo).
    if live_error is not None and (error is None or error >= live_error):
        return live
    x = np.full(len(frames), np.nan)
    y = np.full(len(frames), np.nan)
    x[ok], y[ok] = model.predict(features[ok])
    if drift:
        times = frames["t"].to_numpy(float)
        dx, dy = _interpolate(table, anchor, times)
        x, y = x + dx, y + dy
    return _Estimate(
        x=x,
        y=y,
        method=GEOMETRIC,
        fit_scope=scope,
        check_samples=len(checks),
        live_error_deg=live_error,
        refined_error_deg=error,
        drift_corrected=drift,
        lam=lam,
        noise_px=_noise(checks, px, py) if len(checks) else DEFAULT_NOISE_PX,
    )


def _event_offsets(checks: pd.DataFrame, dx: np.ndarray, dy: np.ndarray) -> pd.DataFrame:
    """Desplazamiento medio (objetivo − predicción) de cada procedimiento de control."""
    return (
        pd.DataFrame(
            {"event": checks["event"].to_numpy(), "t": checks["t"].to_numpy(), "dx": dx, "dy": dy}
        )
        .groupby("event")
        .mean()
        .sort_values("t")
    )


def _interpolate(
    table: pd.DataFrame, anchor: float, times: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Desplazamiento en unos momentos, interpolado entre el ancla (0) y los controles."""
    known_t = np.concatenate([[anchor], table["t"].to_numpy(float)])
    order = np.argsort(known_t)
    known_dx = np.concatenate([[0.0], table["dx"].to_numpy(float)])[order]
    known_dy = np.concatenate([[0.0], table["dy"].to_numpy(float)])[order]
    known_t = known_t[order]
    return np.interp(times, known_t, known_dx), np.interp(times, known_t, known_dy)


def _leave_one_event_out(
    checks: pd.DataFrame, table: pd.DataFrame, anchor: float
) -> tuple[np.ndarray, np.ndarray]:
    """Desplazamiento de cada muestra de control, interpolado sin su propio procedimiento."""
    ox = np.empty(len(checks))
    oy = np.empty(len(checks))
    for event in table.index:
        held = (checks["event"] == event).to_numpy()
        ox[held], oy[held] = _interpolate(
            table.drop(index=event), anchor, checks.loc[held, "t"].to_numpy(float)
        )
    return ox, oy


def _noise(checks: pd.DataFrame, x: np.ndarray, y: np.ndarray) -> float:
    """Ruido de medición: desviación de las muestras de cada punto fijo alrededor de su media.

    Args:
        checks: Muestras de control.
        x: Predicción de cada muestra de control.
        y: Como ``x``.

    Returns:
        Desviación típica por eje en píxeles, o ``DEFAULT_NOISE_PX`` sin datos.
    """
    table = pd.DataFrame({"group": checks["group"].to_numpy(), "x": x, "y": y}).dropna()
    if table.empty:
        return DEFAULT_NOISE_PX
    centered = table[["x", "y"]] - table.groupby("group")[["x", "y"]].transform("mean")
    spread = float(np.sqrt((centered**2).sum(axis=1).mean() / 2))
    return spread if spread > 0 else DEFAULT_NOISE_PX


def _segments(
    t: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    looking: np.ndarray,
    px_per_deg: np.ndarray,
    settings: GazeSettings,
) -> np.ndarray:
    """Tramos para suavizar: cuadros seguidos mirando la pantalla, sin huecos ni saltos.

    Returns:
        Número de tramo de cada cuadro; -1 si no mira la pantalla.
    """
    segment = np.full(len(t), -1)
    current = -1
    previous = None
    for i in np.flatnonzero(looking):
        cut = previous is None or t[i] - t[previous] > MAX_GAP_MS or not looking[previous]
        if not cut:
            dt = (t[i] - t[previous]) / 1000
            speed = np.hypot(x[i] - x[previous], y[i] - y[previous]) / px_per_deg[i] / dt
            cut = speed > settings.params.saccade_deg_per_s
        if cut:
            current += 1
        segment[i] = current
        previous = i
    return segment


def _smooth(
    t: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    segments: np.ndarray,
    px_per_deg: np.ndarray,
    noise_px: float,
    settings: GazeSettings,
) -> tuple[np.ndarray, np.ndarray]:
    """Suavizado de Kalman de paseo aleatorio, hacia adelante y hacia atrás, por tramo."""
    sx = x.copy()
    sy = y.copy()
    measurement = noise_px**2
    for segment in np.unique(segments[segments >= 0]):
        idx = np.flatnonzero(segments == segment)
        if idx.size < 2:
            continue
        dt = np.diff(t[idx], prepend=t[idx[0]]) / 1000
        process = (settings.params.smoothing_deg_per_s * dt * px_per_deg[idx]) ** 2
        for values, out in ((x, sx), (y, sy)):
            z = values[idx]
            n = idx.size
            mean = np.empty(n)
            var = np.empty(n)
            prior_var = np.empty(n)
            mean[0], var[0], prior_var[0] = z[0], measurement, measurement
            for k in range(1, n):
                prior_var[k] = var[k - 1] + process[k]
                gain = prior_var[k] / (prior_var[k] + measurement)
                mean[k] = mean[k - 1] + gain * (z[k] - mean[k - 1])
                var[k] = (1 - gain) * prior_var[k]
            smoothed = mean.copy()
            for k in range(n - 2, -1, -1):
                back = var[k] / prior_var[k + 1]
                smoothed[k] = mean[k] + back * (smoothed[k + 1] - mean[k])
            out[idx] = smoothed
    return sx, sy


def _fixations(
    t: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    segments: np.ndarray,
    px_per_deg: np.ndarray,
    settings: GazeSettings,
) -> np.ndarray:
    """Fijaciones por dispersión (I-DT) dentro de los tramos que miran la pantalla.

    Returns:
        Número de fijación de cada cuadro, desde 0; -1 fuera de una fijación.
    """
    fixation = np.full(len(t), -1)
    number = 0
    looking = np.flatnonzero(segments >= 0)
    # Las fijaciones no cruzan un momento sin mirar la pantalla (los saltos sí las separan solos).
    runs = np.split(looking, np.flatnonzero(np.diff(looking) > 1) + 1) if looking.size else []
    for run in runs:
        start = 0
        while start < run.size:
            end = start
            limit = settings.params.fixation_dispersion_deg * px_per_deg[run[start]]
            while end + 1 < run.size:
                window = run[start : end + 2]
                dispersion = np.ptp(x[window]) + np.ptp(y[window])
                if dispersion > limit:
                    break
                end += 1
            if t[run[end]] - t[run[start]] >= settings.params.fixation_min_ms:
                fixation[run[start : end + 1]] = number
                number += 1
                start = end + 1
            else:
                start += 1
    return fixation
