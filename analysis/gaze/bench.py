"""Banco de pruebas de la mirada: cuánto se equivoca, en grados, y dónde.

Con los cuadros de una sesión (``gaze_feature``) y los puntos que la persona
debía mirar (``gaze_target``), mide dos estimaciones:

- **En vivo**: el punto que dio el motor de la extensión en cada cuadro
  (``raw_x``, ``raw_y``: antes del filtro, con la corrección de deriva).
- **Reajustada**: el estimador geométrico entrenado de nuevo, fuera de línea,
  solo con la calibración inicial, y evaluado en todo lo demás (validaciones,
  vuelta del teclado y comprobaciones de deriva). Sirve para comparar variantes
  del modelo con los mismos datos, sin repetir sesiones.

Desglosa el error por fase, región de la pantalla, cambio de postura de la
cabeza respecto de la calibración y procedimiento a lo largo del tiempo, y da
la precisión (temblor) y los estados de la mirada fuera de la calibración.

Funciones puras sobre DataFrames; ``scripts/gaze_bench.py`` las usa con la base.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from analysis.gaze import GazeSettings
from analysis.gaze.model import fit_geometric
from analysis.gaze.samples import (
    INITIAL,
    TRAINING_PHASES,
    camera_delay,
    geometric_features,
    px_to_deg,
    target_samples,
)

POSE_BINS: dict[str, tuple[float, ...]] = {
    "yaw_deg": (0, 5, 10, 20, np.inf),
    "pitch_deg": (0, 5, 10, 20, np.inf),
    "distance_cm": (0, 3, 6, 10, np.inf),
}
"""Tramos del cambio de postura respecto de la mediana de la calibración."""

_ROWS = ("top", "middle", "bottom")
_COLUMNS = ("left", "center", "right")


@dataclass(frozen=True)
class BenchReport:
    """Resultado del banco de pruebas de una sesión.

    Los errores están en grados; ``live`` es la mirada del motor y ``refit`` la
    del modelo reajustado (``NaN`` donde no hay modelo o en sus datos de entrenamiento).

    Attributes:
        summary: Números generales: cuadros, retraso, errores medios, vuelta del
            teclado, precisión y deriva.
        by_phase: Error por tipo de procedimiento y fase.
        by_region: Error por región de la pantalla (cuadrícula de 3 × 3).
        by_pose: Error según cuánto cambió la cabeza respecto de la calibración.
        over_time: Error de cada procedimiento, en minutos desde la calibración.
        states: Proporción de cada estado de la mirada fuera de los procedimientos.
    """

    summary: dict[str, Any]
    by_phase: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_region: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_pose: pd.DataFrame = field(default_factory=pd.DataFrame)
    over_time: pd.DataFrame = field(default_factory=pd.DataFrame)
    states: pd.DataFrame = field(default_factory=pd.DataFrame)


def _region(samples: pd.DataFrame) -> pd.Series:
    """Región de 3 × 3 de la ventana donde estaba cada objetivo."""
    column = np.clip((3 * samples["target_x"] / samples["viewport_width"]).astype(int), 0, 2)
    row = np.clip((3 * samples["target_y"] / samples["viewport_height"]).astype(int), 0, 2)
    return pd.Series(
        [f"{_ROWS[r]}_{_COLUMNS[c]}" for r, c in zip(row, column, strict=True)],
        index=samples.index,
    )


def _mean_errors(samples: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Muestras y error medio en vivo y reajustado por grupos."""
    return (
        samples.groupby(by, observed=True)
        .agg(
            samples=("live_deg", "size"),
            live_deg=("live_deg", "mean"),
            refit_deg=("refit_deg", "mean"),
        )
        .reset_index()
    )


def _precision_deg(samples: pd.DataFrame, x: str, y: str, css_px_per_cm: float) -> float | None:
    """Raíz cuadrática media de la distancia entre muestras consecutivas de cada punto fijo."""
    squares = []
    for _, group in samples.sort_values("t").groupby("group"):
        gx = group[x].to_numpy(float)
        gy = group[y].to_numpy(float)
        steps = np.hypot(np.diff(gx), np.diff(gy))
        degrees = px_to_deg(steps, group["distance_cm"].to_numpy(float)[1:], css_px_per_cm)
        squares.extend(degrees[np.isfinite(degrees)] ** 2)
    return float(np.sqrt(np.mean(squares))) if squares else None


def evaluate(
    frames: pd.DataFrame,
    targets: pd.DataFrame,
    calibrations: pd.DataFrame,
    settings: GazeSettings,
) -> BenchReport:
    """Mide la mirada de una sesión.

    Args:
        frames: Filas de ``gaze_feature`` de la sesión, en orden de tiempo.
        targets: Filas de ``gaze_target`` (``points`` ya es una lista).
        calibrations: Filas de ``calibration`` (``t``, ``type``, ``camera_delay_ms``).
        settings: Ajustes de la mirada.

    Returns:
        Informe con el error en grados y sus desgloses. Sin objetivos, solo el resumen.
    """
    frames = frames.reset_index(drop=True)
    delay = camera_delay(calibrations)
    samples = target_samples(
        frames,
        targets,
        blink_threshold=settings.blink_threshold,
        pursuit_skip_ms=settings.params.pursuit_skip_ms,
        delay_ms=delay,
    )
    summary: dict[str, Any] = {
        "frames": len(frames),
        "targets": len(targets),
        "samples": len(samples),
        "camera_delay_ms": delay,
    }
    if samples.empty:
        return BenchReport(summary=summary)
    features = geometric_features(frames)
    distance = frames["distance_cm"].astype(float).fillna(settings.viewing_distance_cm)
    samples = samples.assign(distance_cm=distance.to_numpy()[samples["frame"].to_numpy(int)])

    # En vivo: el punto del motor antes del filtro.
    live_x = frames["raw_x"].astype(float).to_numpy()[samples["frame"].to_numpy(int)]
    live_y = frames["raw_y"].astype(float).to_numpy()[samples["frame"].to_numpy(int)]
    live_px = np.hypot(live_x - samples["target_x"], live_y - samples["target_y"])
    samples = samples.assign(
        live_x=live_x,
        live_y=live_y,
        live_deg=px_to_deg(live_px, samples["distance_cm"], settings.css_px_per_cm),
    )

    # Reajustada: entrenada con la última calibración inicial completa, evaluada en lo demás.
    training_mask = (samples["calibration_type"] == INITIAL) & samples["phase"].isin(
        TRAINING_PHASES
    )
    trained_events = samples.loc[training_mask, "event"]
    refit_x = np.full(len(samples), np.nan)
    refit_y = np.full(len(samples), np.nan)
    evaluation = ~samples["phase"].isin(TRAINING_PHASES)
    if len(trained_events):
        last = trained_events.max()
        train = samples[training_mask & (samples["event"] == last)]
        fit = fit_geometric(
            features.loc[train["frame"]],
            train["target_x"],
            train["target_y"],
            train["group"],
            viewport_width=float(train["viewport_width"].iloc[0]),
            css_px_per_cm=settings.css_px_per_cm,
        )
        summary["refit_cv_deg"] = (
            None
            if fit.cv_error_px is None
            else float(
                px_to_deg(fit.cv_error_px, train["distance_cm"].median(), settings.css_px_per_cm)
            )
        )
        summary["refit_residual_lambda"] = fit.lam
        if fit.model is not None:
            calibration_pose = features.loc[train["frame"]].median()
            x, y = fit.model.predict(features.loc[samples["frame"]])
            refit_x = np.where(evaluation, x, np.nan)
            refit_y = np.where(evaluation, y, np.nan)
            for name, column in (
                ("yaw_deg", "yaw"),
                ("pitch_deg", "pitch"),
                ("distance_cm", "distance"),
            ):
                change = np.abs(
                    features.loc[samples["frame"], column].to_numpy(float)
                    - calibration_pose[column]
                )
                samples[f"delta_{name}"] = change
    refit_px = np.hypot(refit_x - samples["target_x"], refit_y - samples["target_y"])
    samples = samples.assign(
        refit_x=refit_x,
        refit_y=refit_y,
        refit_deg=px_to_deg(refit_px, samples["distance_cm"], settings.css_px_per_cm),
    )
    evaluated = samples[evaluation]
    summary.update(_summary(samples, evaluated, settings.css_px_per_cm))
    return BenchReport(
        summary=summary,
        by_phase=_mean_errors(samples, ["calibration_type", "phase"]),
        by_region=_mean_errors(evaluated.assign(region=_region(evaluated)), ["region"])
        if len(evaluated)
        else pd.DataFrame(),
        by_pose=_by_pose(evaluated),
        over_time=_over_time(samples, evaluated),
        states=_states(frames, targets),
    )


def _summary(
    samples: pd.DataFrame, evaluated: pd.DataFrame, css_px_per_cm: float
) -> dict[str, Any]:
    """Errores medios, vuelta del teclado, precisión y deriva del primer al último procedimiento."""

    def mean(series: pd.Series) -> float | None:
        value = series.mean()
        return None if pd.isna(value) else float(value)

    look_away = evaluated[evaluated["phase"] == "look_away"]
    static = evaluated[evaluated["phase"] == "validation"]
    by_event = evaluated.groupby("event")["live_deg"].mean()
    return {
        "live_deg": mean(evaluated["live_deg"]),
        "refit_deg": mean(evaluated["refit_deg"]),
        "live_return_deg": mean(look_away["live_deg"]),
        "refit_return_deg": mean(look_away["refit_deg"]),
        "live_precision_deg": _precision_deg(static, "live_x", "live_y", css_px_per_cm)
        if len(static)
        else None,
        "live_drift_deg": float(by_event.iloc[-1] - by_event.iloc[0])
        if len(by_event) > 1
        else None,
        "training_live_deg": mean(samples[samples["phase"].isin(TRAINING_PHASES)]["live_deg"]),
    }


def _by_pose(evaluated: pd.DataFrame) -> pd.DataFrame:
    """Error según cuánto se alejó la cabeza de la postura de la calibración."""
    parts = []
    for name, edges in POSE_BINS.items():
        column = f"delta_{name}"
        if column not in evaluated:
            continue
        labels = [
            f"{low:g}–{high:g}" if np.isfinite(high) else f"{low:g}+"
            for low, high in zip(edges[:-1], edges[1:], strict=True)
        ]
        labelled = evaluated.assign(
            factor=name,
            change=pd.cut(evaluated[column], list(edges), right=False, labels=labels),
        )
        parts.append(_mean_errors(labelled, ["factor", "change"]))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _over_time(samples: pd.DataFrame, evaluated: pd.DataFrame) -> pd.DataFrame:
    """Error de cada procedimiento, en minutos desde el inicio de la calibración."""
    if evaluated.empty:
        return pd.DataFrame()
    start = samples["t"].min()
    table = (
        evaluated.groupby(["event", "calibration_type"])
        .agg(
            t=("t", "min"),
            samples=("live_deg", "size"),
            live_deg=("live_deg", "mean"),
            refit_deg=("refit_deg", "mean"),
        )
        .reset_index()
    )
    table.insert(2, "minutes", (table.pop("t") - start) / 60_000)
    return table


def _states(frames: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """Proporción de cada estado de la mirada en los cuadros fuera de los procedimientos."""
    if frames.empty:
        return pd.DataFrame()
    times = frames["t"].to_numpy(float)
    outside = np.ones(len(frames), dtype=bool)
    for start, end in zip(targets["t"], targets["t_end"], strict=True):
        outside &= ~((times >= start) & (times <= end))
    counts = frames.loc[outside, "state"].value_counts(normalize=True)
    return counts.rename_axis("state").reset_index(name="share")


def render(report: BenchReport) -> str:
    """Informe en texto para la consola.

    Args:
        report: Informe del banco de pruebas.

    Returns:
        Texto con el resumen y cada tabla, con dos decimales.
    """
    lines = ["Resumen"]
    for key, value in report.summary.items():
        shown = f"{value:.2f}" if isinstance(value, float) else value
        lines.append(f"  {key}: {shown}")
    tables = (
        ("Por fase", report.by_phase),
        ("Por región de la pantalla", report.by_region),
        ("Por cambio de postura respecto de la calibración", report.by_pose),
        ("A lo largo del tiempo", report.over_time),
        ("Estados fuera de los procedimientos", report.states),
    )
    for title, table in tables:
        if len(table):
            lines += ["", title, table.round(2).to_string(index=False)]
    return "\n".join(lines)
