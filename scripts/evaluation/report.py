"""Evaluación completa de un estudio y su informe (preguntas P1 a P4).

Junta las piezas: IUC por versión y su tendencia (P1), relación con el SUS y
casos discrepantes (P2), detección de los problemas sembrados (P3) y acuerdo
con la codificación manual (P4). Los umbrales de éxito no se deciden aquí: se
fijan antes del experimento.
"""

import json
import math
import sqlite3
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import Parameters
from scripts.evaluation import agreement, detection, statistics
from scripts.evaluation.index import COMPONENTS, DEFAULT_HALVES, session_indexes
from scripts.evaluation.repository import StudyResults, load_study_results
from shared.problems import Catalog

MIN_GROUP = 3
"""Sesiones mínimas por versión para compararlas."""


@dataclass
class Evaluation:
    """Resultado de evaluar un estudio.

    Attributes:
        summary: Números de cada pregunta, serializables a JSON.
        tables: Tablas de detalle, por nombre (se exportan a CSV).
        notes: Advertencias para quien lee el informe.
    """

    summary: dict[str, Any]
    tables: dict[str, pd.DataFrame]
    notes: list[str] = field(default_factory=list)


def evaluate(
    connection: sqlite3.Connection,
    study_id: int,
    params: Parameters,
    *,
    catalog: Catalog | None = None,
    affected: Mapping[int, Set[int]] | None = None,
    coding: pd.DataFrame | None = None,
    discrepancy: float = 0.5,
    permutations: int = 10_000,
) -> Evaluation:
    """Evalúa un estudio ya analizado.

    Args:
        connection: Base del estudio.
        study_id: Estudio.
        params: Parámetros del análisis, con ``friction_i_max`` definido.
        catalog: Problemas sembrados, para P3; sin él se omite.
        affected: Problemas que afectaron a cada sesión (experimento simulado).
        coding: Codificación manual leída con ``agreement.read_coding``, para P4.
        discrepancy: Separación de rangos desde la que IUC y SUS discrepan.
        permutations: Permutaciones de la prueba de tendencia.

    Returns:
        La evaluación.

    Raises:
        LookupError: Si el estudio no existe.
        ValueError: Si no hay sesiones guiadas cerradas o falta ``friction_i_max``.
    """
    results = load_study_results(connection, study_id)
    if results.sessions.empty:
        raise ValueError(f"study {study_id} has no closed guided sessions")
    indexes = session_indexes(SqliteAnalysisRepository(connection), results, params)
    evaluation = Evaluation(
        summary={
            "study_id": study_id,
            "sessions": len(results.sessions),
            "versions": results.sessions["version"].value_counts().sort_index().to_dict(),
            "friction_i_max": params.friction_i_max,
            "params_version": params.version,
        },
        tables={"indexes": indexes, "tasks_by_version": _tasks_by_version(results)},
    )
    missing = int(indexes["bui"].isna().sum())
    if missing:
        evaluation.notes.append(
            f"{missing} sesiones sin IUC calculable (sin resultados completos o sin referencias)."
        )
    _index_by_version(evaluation, indexes, permutations)
    _index_and_sus(evaluation, indexes, discrepancy)
    if catalog is not None:
        _detection(evaluation, results, catalog, affected)
    if coding is not None:
        evaluation.summary["p4"] = agreement.coding_agreement(coding)
    return evaluation


def _index_by_version(evaluation: Evaluation, indexes: pd.DataFrame, permutations: int) -> None:
    """P1: el IUC por versión, la comparación, la tendencia y la consistencia."""
    evaluation.tables["index_by_version"] = statistics.describe_by_group(indexes, "bui")
    evaluation.tables["components_by_version"] = (
        indexes.groupby("version")[list(COMPONENTS)].mean().reset_index()
    )
    groups = {
        version: indexes.loc[indexes["version"] == version, "bui"].dropna().tolist()
        for version in statistics.VERSION_ORDER
        if version in set(indexes["version"])
    }
    p1: dict[str, Any] = {}
    usable = {version: values for version, values in groups.items() if len(values) >= MIN_GROUP}
    if len(usable) >= 2:
        p1["comparison"] = statistics.compare_groups(usable)
        p1["trend"] = statistics.jonckheere_terpstra(
            list(usable.values()), permutations=permutations
        ) | {"order": list(usable)}
    else:
        evaluation.notes.append(
            f"P1: hacen falta al menos dos versiones con {MIN_GROUP} sesiones con IUC."
        )
    halves = [f"bui_half_{number}" for number in range(1, len(DEFAULT_HALVES) + 1)]
    p1["split_half"] = statistics.split_half(indexes[halves[0]], indexes[halves[1]]) | {
        "halves": [list(half) for half in DEFAULT_HALVES]
    }
    evaluation.summary["p1"] = p1


def _index_and_sus(evaluation: Evaluation, indexes: pd.DataFrame, discrepancy: float) -> None:
    """P2: correlación IUC–SUS, en total y por versión, y casos discrepantes."""
    evaluation.tables["sus_by_version"] = statistics.describe_by_group(indexes, "sus")
    evaluation.summary["p2"] = {
        "spearman": statistics.spearman(indexes["bui"], indexes["sus"]),
        "by_version": {
            version: statistics.spearman(part["bui"], part["sus"])
            for version, part in indexes.groupby("version", sort=True)
        },
        "discrepancy_threshold": discrepancy,
    }
    discrepant = statistics.discrepant_cases(indexes, "bui", "sus", discrepancy)
    evaluation.tables["discrepant_cases"] = discrepant[
        [
            column
            for column in (
                "session_id",
                "participant_id",
                "version",
                "bui",
                "sus",
                "bui_rank",
                "sus_rank",
                "gap",
            )
            if column in discrepant
        ]
    ]
    evaluation.summary["p2"]["discrepant_cases"] = len(discrepant)


def _detection(
    evaluation: Evaluation,
    results: StudyResults,
    catalog: Catalog,
    affected: Mapping[int, Set[int]] | None,
) -> None:
    """P3: detección de cada problema, falsas alarmas y precisión."""
    sessions = detection.session_detection(results, catalog, affected)
    problems = detection.problem_summary(sessions, catalog)
    alarms = detection.false_alarms(results, catalog)
    evaluation.tables |= {
        "detection_by_session": sessions,
        "detection_by_problem": problems,
        "false_alarms": alarms,
        "unmatched_by_type": detection.unmatched_by_type(results, catalog),
    }
    exposed = sessions[sessions["exposed"]] if len(sessions) else sessions
    seeded = alarms[alarms["precision"].notna()]
    evaluation.summary["p3"] = {
        "exposures": len(exposed),
        "detection_rate": float(exposed["detected"].mean()) if len(exposed) else None,
        "precision": (
            float(seeded["matched"].sum() / seeded["incidents"].sum())
            if seeded["incidents"].sum()
            else None
        ),
        "false_alarms_v0_per_session": _value(alarms, "V0", "unmatched_per_session"),
    }
    if affected is not None and "affected" in exposed:
        hit = exposed[exposed["affected"]]
        evaluation.summary["p3"]["sensitivity"] = (
            float(hit["detected"].mean()) if len(hit) else None
        )
    overlaps = sorted({number for numbers in problems["overlaps"] for number in numbers})
    if overlaps:
        evaluation.notes.append(
            f"P3: los problemas {overlaps} comparten tarea y detectores con otro activo en la "
            "misma versión; un mismo incidente cuenta para ambos."
        )


def _tasks_by_version(results: StudyResults) -> pd.DataFrame:
    """Éxito, duración, pasos y desvíos de cada tarea por versión."""
    versions = dict(zip(results.sessions["session_id"], results.sessions["version"], strict=True))
    tasks = results.task_results.assign(version=results.task_results["session_id"].map(versions))
    if tasks.empty:
        return pd.DataFrame(
            columns=["version", "position", "sessions", "success_rate", "duration_s", "steps"]
        )
    grouped = tasks.groupby(["version", "position"], sort=True)
    return grouped.agg(
        sessions=("session_id", "count"),
        success_rate=("success", "mean"),
        duration_s=("duration_ms", lambda values: values.mean() / 1000),
        steps=("steps", "mean"),
        deviated=("deviation_step", lambda values: values.notna().mean()),
    ).reset_index()


def _value(frame: pd.DataFrame, version: str, column: str) -> Any:
    """Valor de una columna en la fila de una versión, o ``None``."""
    row = frame[frame["version"] == version]
    return None if row.empty else _plain(row.iloc[0][column])


def affected_from_truth(path: Path) -> dict[int, set[int]]:
    """Problemas que afectaron a cada sesión según la verdad de un experimento simulado.

    Args:
        path: ``<base>_ground_truth.json`` de ``scripts.simulate_experiment``.

    Returns:
        ``session_id`` → números de problema.

    Raises:
        ValueError: Si el archivo no trae ``affected_problems``.
    """
    truth = json.loads(path.read_text(encoding="utf-8"))
    sessions = truth.get("sessions", [])
    if not sessions or any("affected_problems" not in item for item in sessions):
        raise ValueError(f"{path} is not the ground truth of a simulated experiment")
    return {int(item["session_id"]): set(item["affected_problems"]) for item in sessions}


def to_json(evaluation: Evaluation) -> str:
    """Resumen y advertencias como JSON estricto (sin NaN)."""
    return json.dumps(
        _plain({"summary": evaluation.summary, "notes": evaluation.notes}),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def write_tables(evaluation: Evaluation, directory: Path) -> list[Path]:
    """Escribe cada tabla de detalle en un CSV.

    Returns:
        Los archivos escritos.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, table in evaluation.tables.items():
        path = directory / f"{name}.csv"
        table.to_csv(path, index=False)
        paths.append(path)
    return paths


def format_report(evaluation: Evaluation) -> str:
    """Informe legible en español.

    Args:
        evaluation: Evaluación.

    Returns:
        Texto con una sección por pregunta.
    """
    s = evaluation.summary
    lines = [
        f"Estudio {s['study_id']}: {s['sessions']} sesiones guiadas "
        + ", ".join(f"{version}: {count}" for version, count in s["versions"].items()),
        f"IUC con friction_i_max = {s['friction_i_max']} (parámetros {s['params_version']})",
        "",
        "P1 · ¿El IUC distingue las versiones?",
    ]
    for row in evaluation.tables["index_by_version"].itertuples():
        lines.append(
            f"  {row.version}: n={row.n}, media={_fmt(row.mean)}, de={_fmt(row.sd)}, "
            f"mediana={_fmt(row.median)}"
        )
    p1 = s["p1"]
    if "comparison" in p1:
        c = p1["comparison"]
        lines += [
            "  Normalidad (Shapiro-Wilk, p): "
            + ", ".join(f"{v}={_fmt(p, 3)}" for v, p in c["shapiro_p"].items()),
            f"  ANOVA: F={_fmt(c['anova']['f'])}, p={_fmt(c['anova']['p'], 4)}, "
            f"eta²={_fmt(c['anova']['eta_squared'], 3)}",
            f"  Kruskal-Wallis: H={_fmt(c['kruskal']['h'])}, p={_fmt(c['kruskal']['p'], 4)}, "
            f"épsilon²={_fmt(c['kruskal']['epsilon_squared'], 3)}",
            f"  Prueba sugerida por la normalidad: {c['suggested']}",
            f"  Tendencia {' > '.join(p1['trend']['order'])} (Jonckheere-Terpstra): "
            f"J={_fmt(p1['trend']['statistic'])} (esperado {_fmt(p1['trend']['expected'])}), "
            f"p={_fmt(p1['trend']['p'], 4)}",
        ]
    half = p1["split_half"]
    lines.append(
        f"  Consistencia por mitades {half['halves']}: r={_fmt(half['r'], 3)}, "
        f"Spearman-Brown={_fmt(half['spearman_brown'], 3)} (n={half['n']})"
    )
    p2 = s["p2"]
    lines += [
        "",
        "P2 · Relación entre IUC y SUS",
        f"  Spearman: rho={_fmt(p2['spearman']['rho'], 3)}, p={_fmt(p2['spearman']['p'], 4)} "
        f"(n={p2['spearman']['n']})",
        f"  Casos discrepantes (rangos separados ≥ {p2['discrepancy_threshold']}): "
        f"{p2['discrepant_cases']}",
    ]
    for row in evaluation.tables["discrepant_cases"].head(10).itertuples():
        higher = "IUC alto, SUS bajo" if row.gap > 0 else "SUS alto, IUC bajo"
        lines.append(
            f"    {row.participant_id} ({row.version}): IUC={_fmt(row.bui)}, "
            f"SUS={_fmt(row.sus)} · {higher}"
        )
    if "p3" in s:
        p3 = s["p3"]
        lines += [
            "",
            "P3 · Detección de los problemas sembrados",
            f"  Detección global: {_pct(p3['detection_rate'])} de {p3['exposures']} exposiciones",
        ]
        if "sensitivity" in p3:
            lines.append(
                f"  Sensibilidad (entre quienes el problema afectó): {_pct(p3['sensitivity'])}"
            )
        lines.append(f"  Precisión en las versiones con problemas: {_pct(p3['precision'])}")
        lines.append(
            f"  Falsas alarmas en V0: {_fmt(p3['false_alarms_v0_per_session'], 2)} por sesión"
        )
        for row in evaluation.tables["detection_by_problem"].itertuples():
            extra = f", sensibilidad {_pct(row.sensitivity)}" if hasattr(row, "sensitivity") else ""
            shared = f" · evidencia compartida con {list(row.overlaps)}" if row.overlaps else ""
            lines.append(
                f"    {row.problem}. {row.name}: {row.detected}/{row.exposed} "
                f"({_pct(row.detection_rate)}){extra}{shared}"
            )
    if "p4" in s:
        p4 = s["p4"]
        lines += [
            "",
            "P4 · Acuerdo con la codificación manual",
            f"  Éxito: acuerdo {_pct(p4['success']['agreement'])}, "
            f"kappa={_fmt(p4['success']['kappa'], 3)} (n={p4['success']['n']})",
            f"  Punto de desvío: acuerdo {_pct(p4['deviation']['agreement'])}, "
            f"kappa={_fmt(p4['deviation']['kappa'], 3)} (n={p4['deviation']['n']}); "
            f"a un paso o menos: {_pct(p4['deviation']['within_one_step'])} "
            f"de {p4['deviation']['both_deviated']}",
        ]
    if evaluation.notes:
        lines += ["", "Advertencias:", *(f"  - {note}" for note in evaluation.notes)]
    return "\n".join(lines)


def _fmt(value: Any, digits: int = 1) -> str:
    """Número redondeado, o un guion si falta."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def _pct(value: Any) -> str:
    """Proporción como porcentaje, o un guion si falta."""
    return "—" if value is None or pd.isna(value) else f"{100 * float(value):.0f} %"


def _plain(value: Any) -> Any:
    """Convierte a tipos de JSON: NaN pasa a ``None`` y los de numpy a los de Python."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
