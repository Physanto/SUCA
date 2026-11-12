"""Detección de los problemas sembrados y falsas alarmas (P3).

Un problema se **expone** en una sesión si está activo en su versión y la
sesión hizo la tarea donde ocurre (todas, si ocurre fuera de las tareas). Se
**detecta** si algún incidente de la sesión es evidencia de él según el
catálogo. Un incidente que no es evidencia de ningún problema activo en su
versión es una **falsa alarma** respecto de los problemas sembrados: puede ser
una dificultad real que el catálogo no prevé, y conviene revisarla.

Con la verdad de un experimento simulado se mide además la sensibilidad de los
detectores: cuántos de los problemas que **afectaron** al participante se
detectaron.
"""

from collections.abc import Mapping, Set

import pandas as pd

from scripts.evaluation.catalog import Catalog
from scripts.evaluation.repository import StudyResults


def incident_matches(results: StudyResults, catalog: Catalog) -> pd.DataFrame:
    """Problemas activos de los que es evidencia cada incidente.

    Args:
        results: Resultados del estudio.
        catalog: Problemas sembrados.

    Returns:
        Los incidentes con ``version`` y ``problems`` (tupla de números, vacía si ninguno).
    """
    versions = dict(zip(results.sessions["session_id"], results.sessions["version"], strict=True))
    incidents = results.incidents.copy()
    incidents["version"] = incidents["session_id"].map(versions)
    incidents["problems"] = [
        tuple(
            problem.number
            for problem in catalog.active(row.version)
            if problem.matches(
                row.type, None if pd.isna(row.position) else int(row.position), row.screen
            )
        )
        for row in incidents.itertuples()
    ]
    return incidents


def session_detection(
    results: StudyResults,
    catalog: Catalog,
    affected: Mapping[int, Set[int]] | None = None,
) -> pd.DataFrame:
    """Exposición y detección de cada problema activo en cada sesión.

    Args:
        results: Resultados del estudio.
        catalog: Problemas sembrados.
        affected: Problemas que afectaron a cada sesión, si se conocen (experimento simulado).

    Returns:
        Una fila por sesión y problema activo: ``session_id``, ``version``,
        ``problem``, ``exposed``, ``detected``, ``evidence`` (incidentes que lo
        respaldan), ``overlaps`` (problemas con evidencia indistinguible) y,
        con la verdad, ``affected``.
    """
    matches = incident_matches(results, catalog)
    rows = []
    for session in results.sessions.itertuples():
        done = set(
            results.task_results.loc[
                results.task_results["session_id"] == session.session_id, "position"
            ]
        )
        own = matches[matches["session_id"] == session.session_id]
        for problem in catalog.active(session.version):
            evidence = int(sum(problem.number in numbers for numbers in own["problems"]))
            row = {
                "session_id": int(session.session_id),
                "participant_id": session.participant_id,
                "version": session.version,
                "problem": problem.number,
                "exposed": problem.task is None or problem.task in done,
                "detected": evidence > 0,
                "evidence": evidence,
                "overlaps": catalog.overlapping(problem, session.version),
            }
            if affected is not None:
                row["affected"] = problem.number in affected.get(int(session.session_id), set())
            rows.append(row)
    return pd.DataFrame(rows)


def problem_summary(detection: pd.DataFrame, catalog: Catalog) -> pd.DataFrame:
    """Tasa de detección de cada problema sobre las sesiones expuestas.

    Args:
        detection: Resultado de :func:`session_detection`.
        catalog: Problemas sembrados.

    Returns:
        Por problema: ``exposed``, ``detected``, ``detection_rate`` y
        ``overlaps``; con la verdad, también ``affected``, ``sensitivity``
        (detectados entre los afectados) y ``detected_unaffected``.
    """
    rows = []
    for problem in catalog.problems:
        own = (
            detection[(detection["problem"] == problem.number) & detection["exposed"]]
            if len(detection)
            else detection
        )
        exposed = len(own)
        detected = int(own["detected"].sum()) if exposed else 0
        overlaps = sorted({number for numbers in own.get("overlaps", []) for number in numbers})
        row = {
            "problem": problem.number,
            "name": problem.name,
            "exposed": exposed,
            "detected": detected,
            "detection_rate": detected / exposed if exposed else None,
            "overlaps": tuple(overlaps),
        }
        if "affected" in detection:
            hit = own[own["affected"]]
            row["affected"] = len(hit)
            row["sensitivity"] = float(hit["detected"].mean()) if len(hit) else None
            row["detected_unaffected"] = int(own.loc[~own["affected"], "detected"].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def false_alarms(results: StudyResults, catalog: Catalog) -> pd.DataFrame:
    """Incidentes que explica algún problema sembrado y los que no, por versión.

    Args:
        results: Resultados del estudio.
        catalog: Problemas sembrados.

    Returns:
        Por versión: ``sessions``, ``incidents``, ``matched``, ``unmatched``,
        ``unmatched_per_session`` y ``precision`` (explicados sobre el total;
        nula en una versión sin problemas sembrados).
    """
    matches = incident_matches(results, catalog)
    rows = []
    for version, sessions in results.sessions.groupby("version", sort=True):
        own = matches[matches["version"] == version]
        matched = int(sum(bool(numbers) for numbers in own["problems"]))
        total = len(own)
        rows.append(
            {
                "version": version,
                "sessions": len(sessions),
                "incidents": total,
                "matched": matched,
                "unmatched": total - matched,
                "unmatched_per_session": (total - matched) / len(sessions),
                "precision": matched / total if total and catalog.active(version) else None,
            }
        )
    return pd.DataFrame(rows)


def unmatched_by_type(results: StudyResults, catalog: Catalog) -> pd.DataFrame:
    """Falsas alarmas por versión y tipo de incidente, para revisarlas.

    Returns:
        ``version``, ``type`` y ``count``, de más a menos.
    """
    matches = incident_matches(results, catalog)
    unmatched = matches[[not numbers for numbers in matches["problems"]]]
    if unmatched.empty:
        return pd.DataFrame(columns=["version", "type", "count"])
    counts = unmatched.groupby(["version", "type"]).size().rename("count").reset_index()
    return counts.sort_values(["version", "count"], ascending=[True, False], ignore_index=True)
