"""Hallazgos de un estudio: qué problemas tuvo la gente, dónde y qué revisar.

Agrupa los incidentes de fricción por pantalla, elemento y tipo, y cuenta a
cuántas personas afectó cada uno. Propone una gravedad y una explicación según
el tipo de incidente; ambas son un punto de partida que el evaluador confirma
mirando la reproducción. La recomendación final la escribe una persona.

- ``build_findings``: un hallazgo por fila, de más a menos personas afectadas.
- ``version_summary`` y ``task_summary``: el contexto (éxito, tiempos, IUC, SUS).
- ``report_markdown``: el informe para descargar, con lo que escribió el evaluador.

No importa Streamlit.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from dashboard.charts import incident_label

#: Por tipo de incidente: qué suele indicar y qué conviene revisar.
INCIDENT_ADVICE: Mapping[str, tuple[str, str]] = {
    "rage_click": (
        "Varios clics rápidos en el mismo lugar: la persona esperaba una respuesta que no llegó "
        "o tardó.",
        "Que el elemento responda enseguida o muestre que está trabajando (indicador de carga, "
        "botón deshabilitado).",
    ),
    "dead_click": (
        "Un clic sin ningún cambio en la página: la persona creyó que el elemento era interactivo.",
        "Que lo que parece clicable lo sea, o que deje de parecerlo (imágenes, textos con estilo "
        "de botón o de enlace).",
    ),
    "navigation_loop": (
        "Ida y vuelta entre pantallas sin avanzar: la persona no encontró lo que buscaba.",
        "Nombres de menús y enlaces, y dónde está la opción que necesitaba.",
    ),
    "long_pause": (
        "Más de unos segundos sin interactuar: la persona leía, dudaba o no sabía qué hacer.",
        "Qué tenía en pantalla en ese momento (con la mirada en la reproducción): textos "
        "confusos, falta de una acción clara.",
    ),
    "hesitation": (
        "El cursor se quedó sobre un elemento sin pulsarlo: la persona dudó de qué hacía.",
        "La etiqueta y el aspecto del elemento: que diga claramente qué pasa al pulsarlo.",
    ),
    "form_error": (
        "El formulario mostró un error de validación.",
        "Que el formato esperado se explique antes de escribir y que el mensaje de error diga "
        "cómo corregirlo.",
    ),
    "field_reentry": (
        "La persona volvió a un campo ya llenado para cambiarlo.",
        "Instrucciones y ejemplos del campo, y si el formulario borra datos al mostrar errores.",
    ),
    "form_abandonment": (
        "La persona empezó a llenar un formulario y salió sin enviarlo.",
        "Largo del formulario, campos que piden datos inesperados y errores que bloquean.",
    ),
    "repeated_search": (
        "Varias búsquedas seguidas sin abrir resultados: no encontraba lo que buscaba.",
        "Que el buscador tolere errores de escritura y sinónimos, y que los resultados sean "
        "claros.",
    ),
    "task_overtime": (
        "La tarea tomó mucho más que la ruta ideal.",
        "En qué paso se desvió (página Tareas) y qué pantallas consumieron el tiempo.",
    ),
    "silent_failure": (
        "La persona envió un formulario, siguió en la misma pantalla y corrigió lo que había "
        "escrito, sin que se registrara un error de validación: el envío falló y el sitio no se "
        "lo dijo de una forma que la captura reconozca (por ejemplo, un aviso general).",
        "En la reproducción, qué mensaje vio. Conviene que el error aparezca junto al campo, con "
        "un texto que diga cómo corregirlo, y que se anuncie a los lectores de pantalla "
        "(role=alert o aria-invalid): sin eso, una persona que no ve el aviso no sabe qué pasó.",
    ),
}

#: Gravedades propuestas, de mayor a menor.
SEVERITIES = ("Alta", "Media", "Baja")

#: Fracción de personas afectadas desde la que un hallazgo es grave o medio.
HIGH_SHARE = 0.5
MEDIUM_SHARE = 0.25
#: Con una sola persona no hay patrón: hacen falta al menos estas para ser grave por alcance.
MIN_PEOPLE_FOR_PATTERN = 2
#: Con menos sesiones por versión, la gravedad propuesta es poco fiable.
FEW_SESSIONS = 3

#: Columnas de ``build_findings``.
FINDING_COLUMNS = [
    "severity", "screen", "element", "incident", "people", "share", "times", "by_version",
    "failed_tasks", "also_in_baseline", "meaning", "check", "examples",
]  # fmt: skip


def element_label(element: Any) -> str:
    """Nombre legible de un elemento: su texto, o su selector si no tiene texto."""
    if not isinstance(element, Mapping):
        return "(sin elemento)"
    return str(element.get("text") or element.get("selector") or "(sin elemento)")


def _clock(ms: float) -> str:
    """mm:ss desde el inicio de la sesión."""
    seconds = max(0, int(ms // 1000))
    return f"{seconds // 60}:{seconds % 60:02d}"


def propose_severity(share: float, people: int, failed_tasks: int) -> str:
    """Gravedad propuesta según su alcance y si hubo tareas no completadas.

    Args:
        share: Fracción de las sesiones de esas versiones con el hallazgo.
        people: Sesiones con el hallazgo.
        failed_tasks: Sesiones afectadas en las que la tarea del incidente no se completó.

    Returns:
        ``Alta`` si alguna tarea afectada no se completó, o si afectó a la mitad o
        más y al menos a ``MIN_PEOPLE_FOR_PATTERN`` personas; ``Media`` si afectó a
        un cuarto o más; si no, ``Baja``.
    """
    if failed_tasks > 0 or (share >= HIGH_SHARE and people >= MIN_PEOPLE_FOR_PATTERN):
        return "Alta"
    if share >= MEDIUM_SHARE:
        return "Media"
    return "Baja"


def build_findings(
    incidents: pd.DataFrame,
    sessions: pd.DataFrame,
    task_results: pd.DataFrame,
    baseline: str | None = "V0",
) -> pd.DataFrame:
    """Hallazgos: incidentes agrupados por pantalla, elemento y tipo.

    Args:
        incidents: ``DashboardData.get_incidents`` del estudio.
        sessions: Sesiones consideradas (``DashboardData.get_sessions``): las
            personas afectadas se cuentan sobre ellas, y los incidentes de otras
            sesiones se ignoran.
        task_results: ``DashboardData.get_task_results`` del estudio.
        baseline: Versión sin problemas sembrados; un hallazgo que también aparece
            en ella se marca (puede ser una falsa alarma o un problema no sembrado).

    Returns:
        Un hallazgo por fila (columnas ``FINDING_COLUMNS``), de más a menos
        personas afectadas: ``people`` (sesiones con el hallazgo), ``share``
        (fracción de las sesiones de esas versiones), ``times`` (incidentes),
        ``by_version`` (``"V0 0/10 · V2 6/10"``), ``failed_tasks`` (sesiones
        afectadas que no completaron la tarea), ``examples`` (hasta 3 lugares
        para verlo en la reproducción).
    """
    if incidents.empty or sessions.empty:
        return pd.DataFrame(columns=FINDING_COLUMNS)
    info = sessions.set_index("session_id")
    rows = incidents[incidents["session_id"].isin(info.index)].copy()
    if rows.empty:
        return pd.DataFrame(columns=FINDING_COLUMNS)
    rows["element_name"] = rows["element"].map(element_label)
    rows["screen"] = rows["screen"].fillna("(sin pantalla)")
    per_version = sessions.groupby("version")["session_id"].nunique()
    failed = (
        set(
            zip(
                task_results.loc[task_results["success"] == False, "session_id"],  # noqa: E712
                task_results.loc[task_results["success"] == False, "task_id"],  # noqa: E712
                strict=True,
            )
        )
        if not task_results.empty
        else set()
    )
    findings = []
    for (screen, element, kind), group in rows.groupby(["screen", "element_name", "type"]):
        affected = group["session_id"].unique()
        versions = info.loc[affected, "version"]
        relevant = per_version[sorted(versions.unique())]
        share = len(affected) / int(relevant.sum())
        counts = versions.value_counts()
        by_version = " · ".join(
            f"{version} {int(counts.get(version, 0))}/{int(total)}"
            for version, total in per_version.items()
        )
        failed_tasks = len(
            {
                row.session_id
                for row in group.itertuples()
                if (row.session_id, row.task_id) in failed
            }
        )
        meaning, check = INCIDENT_ADVICE.get(kind, ("", ""))
        first = group.groupby("session_id")["t"].min().head(3)
        examples = ", ".join(
            f"{info.loc[sid, 'participant_id']} ({_clock(t - info.loc[sid, 'started_at'])})"
            for sid, t in first.items()
        )
        findings.append(
            {
                "severity": propose_severity(share, len(affected), failed_tasks),
                "screen": screen,
                "element": element,
                "incident": incident_label(kind),
                "people": len(affected),
                "share": round(share, 2),
                "times": len(group),
                "by_version": by_version,
                "failed_tasks": failed_tasks,
                "also_in_baseline": baseline is not None and baseline in set(versions),
                "meaning": meaning,
                "check": check,
                "examples": examples,
            }
        )
    order = {severity: index for index, severity in enumerate(SEVERITIES)}
    result = pd.DataFrame(findings, columns=FINDING_COLUMNS)
    result["_order"] = result["severity"].map(order)
    return (
        result.sort_values(["_order", "people", "times"], ascending=[True, False, False])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def version_summary(sessions: pd.DataFrame, task_results: pd.DataFrame) -> pd.DataFrame:
    """Resumen por versión: sesiones, éxito de tareas, incidentes, IUC y SUS.

    Args:
        sessions: Sesiones consideradas (``DashboardData.get_sessions``).
        task_results: ``DashboardData.get_task_results`` del estudio.

    Returns:
        Una fila por versión: ``version``, ``sessions``, ``success_rate`` (vacío
        sin resultados de tareas), ``incidents_per_session``, ``bui`` y ``sus``
        (medias; vacías si no hay).
    """
    columns = ["version", "sessions", "success_rate", "incidents_per_session", "bui", "sus"]
    if sessions.empty:
        return pd.DataFrame(columns=columns)
    results = (
        task_results[task_results["session_id"].isin(sessions["session_id"])]
        if not task_results.empty
        else task_results
    )
    rows = []
    for version, group in sessions.groupby("version"):
        own = results[results["version"] == version] if not results.empty else results
        rows.append(
            {
                "version": version,
                "sessions": len(group),
                "success_rate": float(own["success"].astype(float).mean()) if len(own) else None,
                "incidents_per_session": float(group["incidents"].mean()),
                "bui": pd.to_numeric(group["bui"]).mean(),
                "sus": pd.to_numeric(group["sus_score"]).mean(),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def task_summary(
    task_results: pd.DataFrame, incidents: pd.DataFrame, sessions: pd.DataFrame
) -> pd.DataFrame:
    """Resumen por tarea: éxito, duración y el incidente más frecuente.

    Args:
        task_results: ``DashboardData.get_task_results`` del estudio.
        incidents: ``DashboardData.get_incidents`` del estudio.
        sessions: Sesiones consideradas.

    Returns:
        Una fila por tarea, en orden: ``position``, ``instruction``,
        ``success_rate``, ``median_s`` (duración mediana de las completadas) y
        ``main_incident`` (``"Clic sin respuesta (5)"``, o vacío).
    """
    columns = ["position", "instruction", "success_rate", "median_s", "main_incident"]
    if task_results.empty or sessions.empty:
        return pd.DataFrame(columns=columns)
    results = task_results[task_results["session_id"].isin(sessions["session_id"])]
    own_incidents = incidents[incidents["session_id"].isin(sessions["session_id"])]
    rows = []
    for (position, instruction, task_id), group in results.groupby(
        ["position", "instruction", "task_id"]
    ):
        done = group[group["success"] == True]  # noqa: E712
        kinds = own_incidents.loc[own_incidents["task_id"] == task_id, "type"].value_counts()
        rows.append(
            {
                "position": int(position),
                "instruction": instruction,
                "success_rate": float(group["success"].astype(float).mean()),
                "median_s": float(done["duration_ms"].median()) / 1000 if len(done) else None,
                "main_incident": (
                    f"{incident_label(kinds.index[0])} ({int(kinds.iloc[0])})" if len(kinds) else ""
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _percent(value: Any) -> str:
    """Porcentaje sin decimales, o guion si falta."""
    return "—" if value is None or pd.isna(value) else f"{float(value) * 100:.0f} %"


def _decimal(value: Any, digits: int = 1) -> str:
    """Número con coma decimal, o guion si falta."""
    return (
        "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}".replace(".", ",")
    )


def _cell(value: Any) -> str:
    """Texto seguro para una celda de tabla Markdown."""
    return str(
        "" if value is None or (isinstance(value, float) and pd.isna(value)) else value
    ).replace("|", "/")


def report_markdown(
    study: str,
    versions: Sequence[str],
    summary: pd.DataFrame,
    tasks: pd.DataFrame,
    findings: pd.DataFrame,
    conclusions: str = "",
) -> str:
    """Informe de hallazgos en Markdown, para descargar y adjuntar al informe final.

    Args:
        study: Nombre del estudio.
        versions: Versiones incluidas.
        summary: ``version_summary``.
        tasks: ``task_summary``.
        findings: ``build_findings``, con ``severity`` y ``recommendation`` ya
            revisadas por el evaluador.
        conclusions: Conclusiones escritas por el evaluador.

    Returns:
        Documento Markdown.
    """
    lines = [
        f"# Hallazgos de usabilidad · {study}",
        "",
        f"Versiones: {', '.join(versions)}.",
        "",
        "## Resumen por versión",
        "",
        "| Versión | Sesiones | Tareas completadas | Incidentes por sesión | IUC | SUS |",
        "|---|---|---|---|---|---|",
    ]
    for row in summary.itertuples():
        lines.append(
            f"| {row.version} | {row.sessions} | {_percent(row.success_rate)} | "
            f"{_decimal(row.incidents_per_session)} | {_decimal(row.bui)} | {_decimal(row.sus)} |"
        )
    lines += [
        "",
        "## Tareas",
        "",
        "| Tarea | Completada | Duración mediana | Incidente más frecuente |",
        "|---|---|---|---|",
    ]
    for row in tasks.itertuples():
        median = "—" if row.median_s is None or pd.isna(row.median_s) else f"{row.median_s:.0f} s"
        lines.append(
            f"| {row.position}. {_cell(row.instruction)} | {_percent(row.success_rate)} | "
            f"{median} | {_cell(row.main_incident) or '—'} |"
        )
    lines += ["", "## Hallazgos", ""]
    for index, row in enumerate(findings.itertuples(), start=1):
        recommendation = getattr(row, "recommendation", "") or "Por definir."
        lines += [
            f"### {index}. {row.incident} en «{_cell(row.element)}» ({row.screen})",
            "",
            f"- **Gravedad:** {row.severity}",
            f"- **Personas afectadas:** {row.people} ({_percent(row.share)}); por versión: "
            f"{row.by_version}; {row.times} veces en total",
            f"- **Tareas no completadas entre los afectados:** {row.failed_tasks}",
            f"- **Qué indica:** {row.meaning}",
            f"- **Qué revisar:** {row.check}",
            f"- **Dónde verlo:** {row.examples}",
            f"- **Recomendación:** {recommendation}",
        ]
        if row.also_in_baseline:
            lines.append(
                "- **Aparece también en la versión sin problemas:** posible falsa alarma o "
                "problema no sembrado."
            )
        lines.append("")
    lines += ["## Conclusiones", "", conclusions.strip() or "Por escribir.", ""]
    return "\n".join(lines)
