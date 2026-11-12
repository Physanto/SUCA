"""Mide la atribución contra el guion de una página con objetivos conocidos.

Solo puntúa fijaciones completamente incluidas en el tramo estable de un
objetivo. Los intervalos son semiabiertos: se descartan la sacada inicial y
las fijaciones que cruzan un cambio. El teclado se mide con estados, pues
mirar fuera de pantalla no debería producir fijaciones. No ajusta parámetros
con los mismos datos que evalúa ni confunde ausencia de captura con acierto.
"""

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

PROBABILITY_BINS = (0.0, 0.4, 0.6, 0.8, 0.95, 1.0)
"""Límites de confianza para comparar probabilidad media y frecuencia de acierto."""


@dataclass(frozen=True)
class AttentionScript:
    """Guion validado, compartido con la página de objetivos conocidos.

    Attributes:
        start_selector: Selector del único clic que inicia la ejecución.
        step_ms: Duración de cada objetivo.
        settle_ms: Sacada inicial que no se evalúa.
        targets: Objetivos en orden, con selector, tipo e instrucción.
    """

    start_selector: str
    step_ms: float
    settle_ms: float
    targets: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "AttentionScript":
        """Valida el formato de desarrollo; rechaza tiempos y objetivos incoherentes."""
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("attention script version must be 1")
        start = document.get("start_selector")
        step, settle = document.get("step_ms"), document.get("settle_ms")
        if not isinstance(start, str) or not start.strip():
            raise ValueError("start_selector must be a nonempty selector")
        if (
            any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (step, settle)
            )
            or not 0 <= settle < step
        ):
            raise ValueError("times must be finite with 0 <= settle_ms < step_ms")
        targets = document.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError("targets must be a nonempty list")
        for target in targets:
            if not isinstance(target, dict) or target.get("kind") not in (
                "element",
                "empty",
                "keyboard",
            ):
                raise ValueError("each target needs kind element, empty or keyboard")
            selector = target.get("selector")
            if target["kind"] == "element":
                if not isinstance(selector, str) or not selector.strip():
                    raise ValueError("element targets need a selector")
            elif selector is not None:
                raise ValueError("empty and keyboard targets must have a null selector")
        return cls(start, float(step), float(settle), targets)


@dataclass(frozen=True)
class AttentionBenchReport:
    """Resumen, cobertura por objetivo y calibración de las dos probabilidades.

    Attributes:
        summary: Aciertos, base ingenua y cobertura de captura.
        by_target: Mediciones de cada objetivo, incluso si no tuvo datos.
        by_probability: Confianza media y acierto para p_gaze y p_attention.
        fixations: Detalle de las fijaciones puntuadas y sus predicciones.
    """

    summary: dict[str, Any]
    by_target: pd.DataFrame
    by_probability: pd.DataFrame
    fixations: pd.DataFrame


def _selector(row: Any) -> str | None:
    """Selector de un evento cargado como interacción o como evento completo."""
    value = getattr(row, "selector", None)
    if isinstance(value, str):
        return value
    element = getattr(row, "element", None)
    return element.get("selector") if isinstance(element, dict) else None


def _layout_at(layouts: pd.DataFrame, t: float) -> pd.Series | None:
    """Última disposición vigente, nunca una posterior al punto."""
    if layouts.empty:
        return None
    before = layouts[layouts["t"] <= t]
    return None if before.empty else before.sort_values("t").iloc[-1]


def _ancestors(selector: str, layout: pd.Series | None) -> set[str]:
    """Selector esperado y sus ancestros conocidos, tolerando árboles antiguos."""
    result = {selector}
    if layout is None:
        return result
    elements = layout["elements"]
    index = next((i for i, e in enumerate(elements) if e["selector"] == selector), None)
    visited: set[int] = set()
    while index is not None and index not in visited:
        visited.add(index)
        result.add(elements[index]["selector"])
        parent = elements[index].get("parent")
        index = parent if isinstance(parent, int) and 0 <= parent < len(elements) else None
    return result


def _baseline(row: Any, layout: pd.Series | None) -> str | None:
    """Elemento de menor área que contiene el punto, con scroll y elementos fijos."""
    if layout is None:
        return None
    hits = []
    for element in layout["elements"]:
        box = element["box"]
        x, y = box["x"], box["y"]
        if not element.get("fixed", False):
            x += float(layout["scroll_x"]) - float(getattr(row, "scroll_x", 0))
            y += float(layout["scroll_y"]) - float(getattr(row, "scroll_y", 0))
        if x <= row.x < x + box["w"] and y <= row.y < y + box["h"]:
            hits.append((box["w"] * box["h"], element["selector"]))
    return min(hits, key=lambda hit: hit[0])[1] if hits else None


def _prediction(candidates: pd.DataFrame, column: str) -> tuple[str | None, float] | None:
    """Candidato de mayor probabilidad, incluyendo explícitamente sin asignar."""
    if candidates.empty:
        return None
    best = candidates.loc[candidates[column].idxmax()]
    return (None if pd.isna(best["selector"]) else str(best["selector"]), float(best[column]))


def _reliability(detail: pd.DataFrame) -> pd.DataFrame:
    """Agrupa las predicciones con intervalos [bajo, alto), salvo el último cerrado."""
    rows = []
    for channel in ("p_gaze", "p_attention"):
        if detail.empty:
            continue
        for low, high in zip(PROBABILITY_BINS[:-1], PROBABILITY_BINS[1:], strict=True):
            chosen = detail[
                (detail[f"{channel}_probability"] >= low)
                & (
                    (detail[f"{channel}_probability"] <= high)
                    if high == 1.0
                    else (detail[f"{channel}_probability"] < high)
                )
            ]
            rows.append(
                {
                    "channel": channel,
                    "low": low,
                    "high": high,
                    "fixations": len(chosen),
                    "mean_probability": chosen[f"{channel}_probability"].mean(),
                    "accuracy": chosen[f"{channel}_correct"].mean(),
                }
            )
    return pd.DataFrame(rows)


def evaluate(
    events: pd.DataFrame,
    fixations: pd.DataFrame,
    candidates: pd.DataFrame,
    states: pd.DataFrame,
    layouts: pd.DataFrame,
    script: AttentionScript,
    *,
    start_index: int | None = None,
) -> AttentionBenchReport:
    """Evalúa una ejecución, sin escribir en la base ni modificar los parámetros.

    Args:
        events: Eventos de la sesión con selector o descriptor del elemento.
        fixations: Filas de gaze_fixation, con scroll_x y scroll_y si existen.
        candidates: Filas de gaze_attribution.
        states: Muestras con t y state, incluidas las inválidas.
        layouts: Disposiciones de la sesión con JSON decodificado.
        script: Guion validado de la página.
        start_index: Clic de inicio desde cero si hay varios; exige elección explícita.

    Returns:
        Informe de ambos canales, sin puntuar ausencias de captura como fallos.

    Raises:
        ValueError: Si falta el clic inicial o no se puede elegir una ejecución.
    """
    starts = sorted(
        float(row.t)
        for row in events.itertuples()
        if row.type == "click" and _selector(row) == script.start_selector
    )
    if not starts:
        raise ValueError("no script start click found in this session")
    if start_index is None and len(starts) != 1:
        raise ValueError("multiple start clicks; select --start-index explicitly (from zero)")
    index = 0 if start_index is None else start_index
    if not 0 <= index < len(starts):
        raise ValueError("start index is outside the recorded start clicks")
    origin = starts[index]
    ending = origin + len(script.targets) * script.step_ms
    if index + 1 < len(starts) and starts[index + 1] < ending:
        raise ValueError("another start click overlaps this script execution")
    targets, details = [], []
    for k, target in enumerate(script.targets):
        low = origin + k * script.step_ms + script.settle_ms
        high = origin + (k + 1) * script.step_ms
        stable = (
            fixations[(fixations["t_start"] >= low) & (fixations["t_end"] < high)]
            if not fixations.empty
            else fixations
        )
        samples = states[(states["t"] >= low) & (states["t"] < high) & states["state"].notna()]
        record = {
            "target": k,
            "kind": target["kind"],
            "selector": target["selector"],
            "t_start": low,
            "t_end": high,
            "fixations": len(stable),
            "samples": len(samples),
            "off_screen_share": (samples["state"] == "off_screen").mean(),
            "unassigned_p": stable["unassigned_p"].mean() if len(stable) else None,
        }
        targets.append(record)
        if target["kind"] == "keyboard":
            continue
        for row in stable.itertuples():
            posterior = candidates[candidates["fixation"] == row.fixation]
            layout = _layout_at(layouts, row.t_end)
            expected = target["selector"]
            ancestors = _ancestors(expected, layout) if expected else set()
            resolved = None if pd.isna(row.resolved_selector) else row.resolved_selector
            detail = {
                "target": k,
                "kind": target["kind"],
                "fixation": row.fixation,
                "expected": expected,
                "element_correct": row.element_selector == expected if expected else np.nan,
                "resolved_correct": resolved in ancestors if expected else np.nan,
                "baseline_correct": _baseline(row, layout) == expected
                if layout is not None
                else np.nan,
            }
            for channel in ("p_gaze", "p_attention"):
                predicted = _prediction(posterior, channel)
                detail[f"{channel}_selector"] = predicted[0] if predicted else None
                detail[f"{channel}_probability"] = predicted[1] if predicted else np.nan
                detail[f"{channel}_correct"] = predicted[0] == expected if predicted else np.nan
            details.append(detail)
    detail = pd.DataFrame(details)
    by_target = pd.DataFrame(targets)
    if len(detail):
        for metric in (
            "element_correct",
            "resolved_correct",
            "baseline_correct",
            "p_gaze_correct",
            "p_attention_correct",
        ):
            values = detail.groupby("target")[metric].mean()
            by_target[metric.removesuffix("_correct") + "_accuracy"] = by_target["target"].map(
                values
            )
    summary: dict[str, Any] = {
        "start_t": origin,
        "targets": len(targets),
        "scored_fixations": len(detail),
        "targets_with_samples": int((by_target["samples"] > 0).sum()),
        "targets_with_fixations": int((by_target["fixations"] > 0).sum()),
    }
    for channel in ("p_gaze", "p_attention"):
        summary[f"{channel}_accuracy"] = (
            detail[f"{channel}_correct"].mean() if len(detail) else None
        )
    elements = detail[detail["kind"] == "element"] if len(detail) else detail
    for name in ("element", "resolved", "baseline"):
        summary[f"{name}_accuracy"] = elements[f"{name}_correct"].mean() if len(elements) else None
    summary["baseline_all_accuracy"] = detail["baseline_correct"].mean() if len(detail) else None
    for kind in ("empty", "element"):
        group = by_target[by_target["kind"] == kind]
        summary[f"{kind}_unassigned_p"] = pd.to_numeric(group["unassigned_p"]).mean()
    keyboard = by_target[by_target["kind"] == "keyboard"]
    summary["keyboard_off_screen_share"] = keyboard["off_screen_share"].mean()
    summary["keyboard_samples"] = int(keyboard["samples"].sum())
    return AttentionBenchReport(summary, by_target, _reliability(detail), detail)


def report_to_json(report: AttentionBenchReport) -> dict[str, Any]:
    """Convierte el informe a JSON estricto; las medidas ausentes son null."""
    import json

    summary = {
        key: None if isinstance(value, (float, np.floating)) and not np.isfinite(value) else value
        for key, value in report.summary.items()
    }
    return {
        "summary": summary,
        **{
            name: json.loads(getattr(report, name).to_json(orient="records"))
            for name in ("by_target", "by_probability", "fixations")
        },
    }


def render(report: AttentionBenchReport) -> str:
    """Presenta el resumen, la cobertura por objetivo y la calibración en consola."""
    lines = ["Atribución frente al guion conocido"]
    for key, value in report_to_json(report)["summary"].items():
        lines.append(f"  {key}: {value:.3f}" if isinstance(value, float) else f"  {key}: {value}")
    for title, table in (
        ("Cobertura y estados por objetivo", report.by_target),
        ("Probabilidad media frente a acierto", report.by_probability),
    ):
        if not table.empty:
            lines += ["", title, table.round(3).to_string(index=False)]
    lines += [
        "",
        "p_attention es referencia; para P5 se usa siempre p_gaze.",
        "La verdad supone que se siguió el guion sin interrupciones; revisa la reproducción.",
    ]
    return "\n".join(lines)
