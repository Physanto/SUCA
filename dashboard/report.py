"""Informe de resultados de un estudio: un único archivo HTML, redactado y con gráficas.

Reúne lo que el panel muestra en varias páginas en un documento que se lee de
arriba abajo, se proyecta o se imprime a PDF:

1. **Veredicto** de una mirada: SUS, tareas, IUC y hallazgos graves, con el
   criterio con que se lee.
2. **SUS** interpretado y desglosado por ítem.
3. **Índice de usabilidad conductual** y **tareas**.
4. **Hallazgos** redactados, con lo que significan y qué revisar.
5. **Mapas de calor** de las pantallas con problemas y **línea de tiempo**.
6. **Heurísticas de Nielsen**, como relación orientativa por indicios.
7. **Límites**: qué se midió y qué no.

El archivo no necesita internet: las gráficas son SVG y los mapas de calor van
incrustados. Contiene capturas y datos de participantes: se genera en local y no
debe subirse (ver las reglas de privacidad del proyecto).

``render`` es una función pura sobre ``ReportInputs``; quien reúne los datos es
``dashboard/report_inputs.py``. No importa Streamlit.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape
from typing import Any

import pandas as pd

from dashboard import nielsen, report_svg, sus
from dashboard.charts import INCIDENT_LABELS, incident_label
from dashboard.findings import FEW_SESSIONS, SEVERITIES
from dashboard.report_svg import Bar, TimelineRow

SUCCESS_GOOD = 0.8
"""Fracción de tareas completadas desde la que la señal es buena."""

SUCCESS_BAD = 0.5
"""Fracción de tareas completadas por debajo de la que la señal es mala."""

HIGH_FINDINGS_BAD = 3
"""Hallazgos graves desde los que la señal es mala."""

TOP_FINDINGS = 10
"""Hallazgos que se redactan completos; el resto va en una tabla."""

CRITERIA = (
    "Criterio de esta lectura (provisional, no un umbral del proyecto): el SUS se califica con "
    "las bandas de la literatura; las tareas son buenas desde el 80 % completadas y malas por "
    "debajo del 50 %; los hallazgos graves son buenos si no hay ninguno y malos desde 3. Si "
    "alguna señal es mala, la lectura es de problemas serios; si todas las disponibles son "
    "buenas, de un sistema usable; si no, mixta."
)
"""Cómo se llega al veredicto, para que se pueda discutir."""


@dataclass(frozen=True)
class HeatmapFigure:
    """Un mapa de calor ya dibujado.

    Attributes:
        screen: Pantalla normalizada.
        layer: Capa en español (Clics, Mirada).
        data_uri: Imagen incrustada (``data:image/jpeg;base64,…``).
        caption: Pie de la imagen: cuántas sesiones y puntos.
    """

    screen: str
    layer: str
    data_uri: str
    caption: str


@dataclass(frozen=True)
class ReportInputs:
    """Todo lo que necesita el informe, ya reunido.

    Attributes:
        study: Nombre del estudio.
        system: Sistema evaluado, o texto vacío.
        generated_at: Fecha y hora de generación, en texto.
        source: De dónde salen los datos (nombre de la base).
        versions: Versiones incluidas.
        sessions: ``DashboardData.get_sessions`` de las sesiones incluidas.
        summary: ``findings.version_summary``.
        tasks: ``findings.task_summary``.
        findings: ``findings.build_findings`` con la gravedad y la ``recommendation``
            ya revisadas por el evaluador.
        incidents: Incidentes de las sesiones incluidas.
        index: ``DashboardData.get_usability_index`` de esas sesiones.
        sus_answers: ``DashboardData.get_sus_answers`` de esas sesiones.
        timelines: Una fila por sesión para la línea de tiempo.
        timeline_legend: Tipos de incidente de la línea de tiempo, en orden de índice.
        heatmaps: Mapas de calor de las pantallas con problemas.
        conclusions: Conclusiones escritas por el evaluador.
    """

    study: str
    system: str
    generated_at: str
    source: str
    versions: Sequence[str]
    sessions: pd.DataFrame
    summary: pd.DataFrame
    tasks: pd.DataFrame
    findings: pd.DataFrame
    incidents: pd.DataFrame
    index: pd.DataFrame
    sus_answers: pd.DataFrame
    timelines: Sequence[TimelineRow] = field(default_factory=tuple)
    timeline_legend: Sequence[str] = field(default_factory=tuple)
    heatmaps: Sequence[HeatmapFigure] = field(default_factory=tuple)
    conclusions: str = ""


@dataclass(frozen=True)
class Card:
    """Una señal del veredicto.

    Attributes:
        title: Qué mide.
        value: Valor principal.
        note: Aclaración corta.
        tone: ``good``, ``ok``, ``bad`` o ``muted`` (sin dato).
    """

    title: str
    value: str
    note: str
    tone: str


@dataclass(frozen=True)
class Verdict:
    """Lectura de una mirada de los resultados.

    Attributes:
        tone: ``good``, ``ok``, ``bad`` o ``muted``.
        headline: Frase principal.
        cards: Las señales en que se apoya.
        paragraphs: Lectura redactada.
    """

    tone: str
    headline: str
    cards: Sequence[Card]
    paragraphs: Sequence[str]


# --- Formato ---------------------------------------------------------------------------------


def _e(value: Any) -> str:
    """Texto escapado para HTML; vacío si falta."""
    return "" if _missing(value) else escape(str(value))


def _missing(value: Any) -> bool:
    """Si un valor falta (``None`` o NaN)."""
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA


def _num(value: Any, digits: int = 1) -> str:
    """Número con coma decimal, o un guion si falta."""
    return "—" if _missing(value) else f"{float(value):.{digits}f}".replace(".", ",")


def _pct(value: Any) -> str:
    """Fracción como porcentaje sin decimales, o un guion si falta."""
    return "—" if _missing(value) else f"{float(value) * 100:.0f} %"


def _plural(count: int, singular: str, plural: str) -> str:
    """``1 persona`` o ``3 personas``."""
    return f"{count} {singular if count == 1 else plural}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], caption: str) -> str:
    """Tabla accesible; las celdas ya vienen como HTML."""
    head = "".join(f'<th scope="col">{_e(header)}</th>' for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (
        f'<table><caption class="sr">{_e(caption)}</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def _chip(text: str, tone: str) -> str:
    """Etiqueta de color con texto: el estado no depende solo del color."""
    return f'<span class="chip {escape(tone)}">{_e(text)}</span>'


# --- Veredicto -------------------------------------------------------------------------------


def verdict(inputs: ReportInputs) -> Verdict:
    """Lectura de una mirada: las señales y qué dicen en conjunto.

    Args:
        inputs: Datos del informe.

    Returns:
        El veredicto con sus señales y su redacción. Sin ninguna señal, un
        veredicto sin tono que lo dice.
    """
    scores = (
        inputs.sus_answers["score"] if "score" in inputs.sus_answers else pd.Series(dtype=float)
    )
    reading = sus.summarize(list(scores))
    rating = reading["rating"]
    results = inputs.tasks
    tasks_known = len(results) > 0 and results["success_rate"].notna().any()
    success = float(results["success_rate"].mean()) if tasks_known else None
    bui = pd.to_numeric(inputs.sessions["bui"], errors="coerce").dropna()
    findings = inputs.findings
    high = int((findings["severity"] == SEVERITIES[0]).sum()) if len(findings) else 0

    cards = [
        Card(
            "SUS",
            f"{_num(reading['mean'], 0)} · {rating.label} ({rating.grade})" if rating else "—",
            (rating.versus_average if rating else "Nadie respondió el SUS."),
            rating.tone if rating else "muted",
        ),
        Card(
            "Tareas completadas",
            _pct(success),
            "Promedio de las tareas del estudio." if tasks_known else "Sin resultados por tarea.",
            "muted"
            if success is None
            else "good"
            if success >= SUCCESS_GOOD
            else "bad"
            if success < SUCCESS_BAD
            else "ok",
        ),
        Card(
            "IUC medio",
            _num(bui.mean(), 0) if len(bui) else "—",
            "De 0 a 100; mayor es mejor." if len(bui) else "Sin IUC calculado.",
            "muted",
        ),
        Card(
            "Hallazgos graves",
            str(high) if len(findings) else "—",
            f"de {len(findings)} hallazgos" if len(findings) else "Sin hallazgos.",
            "muted"
            if not len(findings)
            else "good"
            if high == 0
            else "bad"
            if high >= HIGH_FINDINGS_BAD
            else "ok",
        ),
    ]
    tones = [card.tone for card in cards if card.tone != "muted"]
    if not tones:
        tone, headline = "muted", "Sin datos suficientes para una lectura."
    elif "bad" in tones:
        tone, headline = "bad", "Los datos apuntan a problemas serios de usabilidad."
    elif all(item == "good" for item in tones):
        tone, headline = "good", "Los datos apuntan a un sistema usable."
    else:
        tone, headline = "ok", "Resultado mixto: hay cosas que funcionan y problemas que corregir."

    people = int(inputs.sessions["session_id"].nunique()) if len(inputs.sessions) else 0
    paragraphs = [f"Participaron {_plural(people, 'sesión', 'sesiones')}."]
    if rating:
        paragraphs.append(
            f"El SUS medio es {_num(reading['mean'], 0)}: calificación «{rating.label}», nota "
            f"{rating.grade}. {rating.versus_average}"
        )
    if reading["warning"]:
        paragraphs.append(reading["warning"])
    if tasks_known:
        done = float(results["success_rate"].mean())
        paragraphs.append(
            f"Las tareas se completaron en promedio en el {_pct(done)} de los intentos."
        )
    if len(findings):
        top = findings.iloc[0]
        paragraphs.append(
            f"El sistema marcó {_plural(len(findings), 'hallazgo', 'hallazgos')}, "
            f"{high} de gravedad alta. El más importante: {_e(top['incident']).lower()} en "
            f"«{_e(top['element'])}» ({_e(top['screen'])}), que afectó a "
            f"{_plural(int(top['people']), 'persona', 'personas')}."
        )
    if (
        len(inputs.sessions)
        and int(inputs.sessions.groupby("version")["session_id"].nunique().min()) < FEW_SESSIONS
    ):
        paragraphs.append(
            f"Hay versiones con menos de {FEW_SESSIONS} sesiones: la gravedad propuesta y esta "
            "lectura son poco fiables. Úsalas como guía de qué revisar, no como conclusión."
        )
    return Verdict(tone, headline, cards, paragraphs)


def _verdict_section(inputs: ReportInputs) -> str:
    """Sección del veredicto con sus señales."""
    reading = verdict(inputs)
    cards = "".join(
        f'<div class="card {card.tone}"><div class="card-title">{_e(card.title)}</div>'
        f'<div class="card-value">{_e(card.value)}</div>'
        f'<div class="card-note">{_e(card.note)}</div></div>'
        for card in reading.cards
    )
    paragraphs = "".join(f"<p>{paragraph}</p>" for paragraph in reading.paragraphs)
    return (
        '<section id="veredicto"><h2>Lectura general</h2>'
        f'<p class="headline {reading.tone}">{_e(reading.headline)}</p>'
        f'<div class="cards">{cards}</div>{paragraphs}'
        f'<p class="muted small">{_e(CRITERIA)}</p></section>'
    )


def _conclusions_section(inputs: ReportInputs) -> str:
    """Conclusiones del evaluador, si las escribió."""
    if not inputs.conclusions.strip():
        return ""
    body = "".join(f"<p>{_e(line)}</p>" for line in inputs.conclusions.strip().splitlines() if line)
    return f'<section id="conclusiones"><h2>Conclusiones del evaluador</h2>{body}</section>'


# --- SUS -------------------------------------------------------------------------------------


def _sus_section(inputs: ReportInputs) -> str:
    """El SUS: calificación, respuestas sobre la escala y desglose por ítem."""
    answers = inputs.sus_answers
    reading = sus.summarize(list(answers["score"]) if "score" in answers else [])
    parts = ['<section id="sus"><h2>SUS: percepción de usabilidad</h2>']
    parts.append(
        "<p>El SUS (<em>System Usability Scale</em>) es un cuestionario de 10 preguntas que "
        "responde cada persona al terminar. Da un puntaje de 0 a 100: la referencia histórica "
        "es 68, y se califica como Pobre (menos de 51), Aceptable, Bueno (desde 71) o "
        "Excelente (desde 86).</p>"
    )
    if reading["rating"] is None:
        parts.append(f'<p class="note">{_e(reading["warning"])}</p></section>')
        return "".join(parts)
    rating = reading["rating"]
    parts.append(
        f'<p class="big">{_chip(f"{rating.label} · nota {rating.grade}", rating.tone)} '
        f"<strong>{_num(reading['mean'], 1)}</strong> de 100 "
        f"<span class='muted'>({_plural(reading['count'], 'respuesta', 'respuestas')}; "
        f"de {_num(reading['min'], 0)} a {_num(reading['max'], 0)})</span></p>"
    )
    parts.append(f"<p>{_e(rating.versus_average)}</p>")
    if reading["warning"]:
        parts.append(f'<p class="note">{_e(reading["warning"])}</p>')
    scores = [
        (f"{row.participant_id} · {row.version}", float(row.score)) for row in answers.itertuples()
    ]
    parts.append(report_svg.sus_scale(scores))
    by_version = []
    for version, group in answers.groupby("version", sort=True):
        summary = sus.summarize(list(group["score"]))
        item = summary["rating"]
        by_version.append(
            [
                _e(version),
                str(summary["count"]),
                _num(summary["mean"], 1),
                _chip(f"{item.label} ({item.grade})", item.tone) if item else "—",
                _e(item.versus_average) if item else "",
            ]
        )
    if len(by_version) > 1:
        parts.append(
            _table(
                ["Versión", "Respuestas", "SUS medio", "Calificación", "Frente al promedio"],
                by_version,
                "SUS por versión",
            )
        )
    breakdown = sus.item_breakdown(answers)
    if not breakdown.empty:
        bars = [
            Bar(
                f"{int(row.item)}. {row.text}",
                float(row.mean),
                f"{_num(row.mean, 1)} de 4",
                "bad" if row.mean < 2 else "ok" if row.mean < 3 else "good",
            )
            for row in breakdown.itertuples()
        ]
        parts.append(
            "<h3>Qué ítems restaron más</h3>"
            "<p>Cada ítem aporta de 0 a 4 puntos al SUS (4 es lo mejor, sea el ítem positivo o "
            "negativo). Los de arriba son los que más bajaron el puntaje: dicen qué aspecto "
            "percibió peor la gente.</p>"
            + report_svg.bar_chart(
                bars,
                maximum=4,
                title="Aporte medio de cada ítem del SUS",
                description="Barras de 0 a 4 con lo que aporta cada ítem, de menor a mayor.",
                width=820,
                label_width=340,
            )
            + '<p class="muted small">Los ítems son un resumen de las preguntas del SUS, no su '
            "texto validado.</p>"
        )
    parts.append("</section>")
    return "".join(parts)


# --- Índice y tareas -------------------------------------------------------------------------


def _index_section(inputs: ReportInputs) -> str:
    """IUC por versión y sus componentes."""
    index = inputs.index
    parts = ['<section id="iuc"><h2>Índice de usabilidad conductual (IUC)</h2>']
    parts.append(
        "<p>El IUC resume, de 0 a 100, lo que la persona <em>hizo</em>: si completó las "
        "tareas, qué tan rápido y por qué camino, y cuánta fricción tuvo. Complementa al SUS "
        "(lo que <em>dijo</em>), no lo reemplaza.</p>"
    )
    if index.empty or pd.to_numeric(index["bui"], errors="coerce").isna().all():
        parts.append(
            '<p class="note">Sin IUC: el análisis lo guarda cuando <code>friction_i_max</code> '
            "está definido en <code>parameters.yaml</code> (se fija con el piloto).</p></section>"
        )
        return "".join(parts)
    grouped = index.groupby("version", sort=True)[
        ["effectiveness", "time_efficiency", "path_efficiency", "friction", "bui"]
    ].mean()
    bars = [
        Bar(str(version), float(row.bui), _num(row.bui, 0)) for version, row in grouped.iterrows()
    ]
    parts.append(
        report_svg.bar_chart(
            bars,
            maximum=100,
            title="IUC medio por versión",
            description="Barras de 0 a 100 con el IUC medio de cada versión.",
        )
    )
    rows = [
        [_e(version), *[_num(row[name], 0) for name in grouped.columns]]
        for version, row in grouped.iterrows()
    ]
    parts.append(
        _table(
            ["Versión", "Efectividad", "Tiempo", "Camino", "Fricción", "IUC"],
            rows,
            "Componentes del IUC por versión",
        )
    )
    parts.append(
        '<p class="muted small">Efectividad: tareas completadas. Tiempo y camino: qué tan cerca '
        "de la ruta ideal grabada. Fricción: incidentes por minuto de tarea (mayor es menos "
        "fricción).</p></section>"
    )
    return "".join(parts)


def _tasks_section(inputs: ReportInputs) -> str:
    """Éxito y tiempo de cada tarea."""
    tasks = inputs.tasks
    parts = ['<section id="tareas"><h2>Tareas</h2>']
    if tasks.empty:
        parts.append('<p class="note">Sin resultados por tarea: solo las sesiones guiadas '
                     "analizadas los tienen.</p></section>")  # fmt: skip
        return "".join(parts)
    bars = [
        Bar(
            f"Tarea {int(row.position)}",
            float(row.success_rate),
            _pct(row.success_rate),
            "good" if row.success_rate >= SUCCESS_GOOD
            else "bad" if row.success_rate < SUCCESS_BAD else "ok",
        )
        for row in tasks.itertuples()
    ]  # fmt: skip
    parts.append(
        report_svg.bar_chart(
            bars,
            maximum=1,
            title="Tareas completadas",
            description="Fracción de intentos en que se completó cada tarea.",
        )
    )
    rows = [
        [
            str(int(row.position)),
            _e(row.instruction),
            _pct(row.success_rate),
            "—" if _missing(row.median_s) else f"{row.median_s:.0f} s",
            _e(row.main_incident) or "—",
        ]
        for row in tasks.itertuples()
    ]
    parts.append(
        _table(
            ["Tarea", "Instrucción", "Completada", "Duración mediana", "Incidente más frecuente"],
            rows,
            "Resumen por tarea",
        )
    )
    parts.append("</section>")
    return "".join(parts)


# --- Hallazgos -------------------------------------------------------------------------------


def _findings_section(inputs: ReportInputs) -> str:
    """Hallazgos redactados, de más a menos graves."""
    findings = inputs.findings
    parts = ['<section id="hallazgos"><h2>Hallazgos</h2>']
    if findings.empty:
        parts.append('<p class="note">No hay incidentes en estas sesiones. ¿Ya se analizaron?</p>'
                     "</section>")  # fmt: skip
        return "".join(parts)
    counts = findings["severity"].value_counts()
    parts.append(
        "<p>"
        + " · ".join(
            f"{counts.get(severity, 0)} de gravedad {severity.lower()}" for severity in SEVERITIES
        )
        + ". La gravedad es una propuesta del sistema (alcance y tareas no completadas) que el "
        "evaluador puede cambiar en el panel.</p>"
    )
    if not inputs.incidents.empty:
        by_type = inputs.incidents["type"].value_counts()
        bars = [
            Bar(incident_label(kind), float(count), str(int(count)))
            for kind, count in by_type.items()
        ]
        parts.append(
            report_svg.bar_chart(
                bars,
                maximum=float(by_type.max()),
                title="Incidentes por tipo",
                description="Cantidad de incidentes de cada tipo en todas las sesiones.",
            )
        )
    for number, row in enumerate(findings.head(TOP_FINDINGS).itertuples(), start=1):
        tone = {"Alta": "bad", "Media": "ok", "Baja": "muted"}.get(row.severity, "muted")
        baseline = (
            '<p class="small muted">También apareció en la versión sin problemas sembrados: '
            "puede ser una falsa alarma o un problema que nadie sembró.</p>"
            if row.also_in_baseline
            else ""
        )
        failed = (
            f"<li><strong>Tareas no completadas:</strong> {int(row.failed_tasks)} de las "
            "sesiones afectadas.</li>"
            if row.failed_tasks
            else ""
        )
        recommendation = (
            f"<li><strong>Recomendación:</strong> {_e(row.recommendation)}</li>"
            if _e(getattr(row, "recommendation", ""))
            else ""
        )
        parts.append(
            f'<article class="finding"><h3>{number}. {_e(row.incident)} en «{_e(row.element)}» '
            f"{_chip(f'Gravedad {row.severity.lower()}', tone)}</h3>"
            f'<p class="small muted">Pantalla {_e(row.screen)} · '
            f"{_plural(int(row.people), 'persona', 'personas')} ({_pct(row.share)} de las sesiones)"
            f" · {int(row.times)} veces · {_e(row.by_version)}</p>"
            f"<ul><li><strong>Qué suele indicar:</strong> {_e(row.meaning)}</li>"
            f"<li><strong>Qué revisar:</strong> {_e(row.check)}</li>"
            f"{failed}{recommendation}"
            f"<li><strong>Dónde verlo en la reproducción:</strong> {_e(row.examples)}</li></ul>"
            f"{baseline}</article>"
        )
    rest = findings.iloc[TOP_FINDINGS:]
    if len(rest):
        rows = [
            [_e(r.severity), _e(r.incident), _e(r.element), _e(r.screen), str(int(r.people))]
            for r in rest.itertuples()
        ]
        parts.append(
            "<h3>Otros hallazgos</h3>"
            + _table(
                ["Gravedad", "Incidente", "Elemento", "Pantalla", "Personas"],
                rows,
                "Otros hallazgos",
            )
        )
    parts.append("</section>")
    return "".join(parts)


# --- Mapas y línea de tiempo -----------------------------------------------------------------


def _maps_section(inputs: ReportInputs) -> str:
    """Mapas de calor de las pantallas con problemas, y la línea de tiempo."""
    parts = ['<section id="mapas"><h2>Dónde pasó</h2>']
    if inputs.heatmaps:
        parts.append(
            "<p>Mapas de calor de las pantallas con hallazgos, con todas las sesiones juntas. "
            "Más rojo es más concentración. La mirada tiene un error de unos 2 a 4 grados "
            "(100 a 150 píxeles): se lee por zonas y elementos grandes, no por botones "
            "pequeños.</p>"
        )
        for screen in dict.fromkeys(figure.screen for figure in inputs.heatmaps):
            parts.append(f'<h3>Pantalla {_e(screen)}</h3><div class="maps">')
            for figure in (f for f in inputs.heatmaps if f.screen == screen):
                parts.append(
                    f'<figure><img src="{escape(figure.data_uri)}" '
                    f'alt="Mapa de calor de {_e(figure.layer.lower())} '
                    f'en la pantalla {_e(screen)}">'
                    f"<figcaption><strong>{_e(figure.layer)}.</strong> {_e(figure.caption)}"
                    "</figcaption></figure>"
                )
            parts.append("</div>")
    else:
        parts.append('<p class="note">Sin mapas de calor: no hubo pantallas con hallazgos o '
                     "con puntos registrados.</p>")  # fmt: skip
    if inputs.timelines:
        parts.append(
            "<h3>Línea de tiempo de las sesiones</h3>"
            "<p>Cada fila es una sesión a su propia escala, desde su primera tarea (sin la "
            "calibración inicial). Las franjas son las tareas y los puntos, los incidentes.</p>"
            + report_svg.timeline(inputs.timelines, inputs.timeline_legend)
        )
    parts.append("</section>")
    return "".join(parts)


# --- Nielsen y límites -----------------------------------------------------------------------


def _nielsen_section(inputs: ReportInputs) -> str:
    """Relación orientativa con las heurísticas de Nielsen."""
    table = nielsen.heuristic_table(inputs.incidents, INCIDENT_LABELS)
    maximum = float(table["signs"].max()) if len(table) else 0.0
    rows = []
    for row in table.itertuples():
        note = (
            _e(row.from_types)
            if row.signs
            else (
                "Casi no se observa en el comportamiento."
                if not row.observable
                else "Sin indicios."
            )
        )
        rows.append([str(row.number), _e(row.heuristic), str(row.signs), str(row.sessions), note])
    bars = [
        Bar(f"{row.number}. {row.heuristic}", float(row.signs), str(row.signs),
            "accent" if row.observable else "muted")
        for row in table.itertuples()
    ]  # fmt: skip
    return (
        '<section id="nielsen"><h2>Heurísticas de Nielsen: indicios</h2>'
        f'<p class="note">{_e(nielsen.CAVEAT)}</p>'
        + (
            report_svg.bar_chart(
                bars,
                maximum=maximum or 1.0,
                title="Indicios por heurística de Nielsen",
                description="Incidentes que apuntan a cada una de las 10 heurísticas.",
                width=900,
                label_width=400,
            )
            if maximum
            else '<p class="muted">Sin incidentes que relacionar.</p>'
        )
        + _table(
            ["N.º", "Heurística", "Indicios", "Sesiones", "De qué incidentes"],
            rows,
            "Indicios por heurística de Nielsen",
        )
        + "</section>"
    )


def _limits_section(inputs: ReportInputs) -> str:
    """Qué se midió, con qué y qué no."""
    people = int(inputs.sessions["session_id"].nunique()) if len(inputs.sessions) else 0
    return (
        '<section id="limites"><h2>Alcance y límites</h2><ul>'
        f"<li><strong>Muestra:</strong> {_plural(people, 'sesión', 'sesiones')}. Con pocas "
        "personas los resultados son casos y no estadística: sirven para encontrar problemas, no "
        "para generalizar.</li>"
        "<li><strong>Qué mide el sistema:</strong> lo que la persona hace (clics, cursor, "
        "navegación, errores, tiempos) y, con cámara, hacia dónde mira. No lee lo que escribe "
        "ni guarda imágenes del rostro.</li>"
        "<li><strong>Los hallazgos son indicios:</strong> el sistema los propone y el evaluador "
        "los confirma en la reproducción.</li>"
        "<li><strong>No se midió:</strong> contraste de color, texto alternativo, etiquetas de "
        "los campos ni navegación con teclado. Esto no es una auditoría de accesibilidad.</li>"
        "<li><strong>Apps con iframes o <em>shadow DOM</em>:</strong> lo que está dentro no se "
        "captura.</li></ul></section>"
    )


# --- Documento -------------------------------------------------------------------------------

STYLE = """
:root{--bg:#fff;--fg:#1d2733;--muted:#5b6776;--line:#dfe4ea;--card:#f6f8fa;--accent:#2f6fdb;
--good:#1f8a4c;--good2:#16703c;--ok:#b7791f;--bad:#c0392b;--track:#eef1f4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 20px 60px}
header.cover{border-bottom:3px solid var(--accent);padding-bottom:14px;margin-bottom:8px}
header.cover h1{margin:0 0 4px;font-size:30px}
nav.toc{display:flex;flex-wrap:wrap;gap:6px 14px;margin:14px 0 4px;font-size:14px}
nav.toc a{color:var(--accent);text-decoration:none}
nav.toc a:hover,nav.toc a:focus{text-decoration:underline}
section{margin-top:34px}
h2{font-size:22px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:17px;margin:22px 0 6px}
p,li{max-width:80ch}
.muted{color:var(--muted)}.small{font-size:14px}.big{font-size:19px}
.note{background:#fff8e6;border-left:4px solid var(--ok);padding:8px 12px;border-radius:4px}
.headline{font-size:21px;font-weight:600;padding:10px 14px;border-radius:6px;border-left:6px solid}
.headline.good{background:#e8f5ee;border-color:var(--good)}
.headline.ok{background:#fff8e6;border-color:var(--ok)}
.headline.bad{background:#fdecea;border-color:var(--bad)}
.headline.muted{background:var(--card);border-color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:14px 0}
.card{background:var(--card);border-radius:8px;padding:12px 14px;border-top:5px solid var(--muted)}
.card.good{border-color:var(--good)}.card.ok{border-color:var(--ok)}.card.bad{border-color:var(--bad)}
.card-title{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.card-value{font-size:24px;font-weight:700}.card-note{font-size:13px;color:var(--muted)}
.chip{display:inline-block;padding:1px 9px;border-radius:99px;font-size:13px;font-weight:600;
color:#fff;background:var(--muted);vertical-align:middle}
.chip.good{background:var(--good)}.chip.ok{background:var(--ok)}.chip.bad{background:var(--bad)}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--card)}
.sr{position:absolute;left:-9999px}
article.finding{border:1px solid var(--line);border-radius:8px;padding:6px 16px 10px;margin:14px 0;
break-inside:avoid}
article.finding h3{margin-top:10px}
figure{margin:10px 0}figure img{max-width:100%;border:1px solid var(--line);border-radius:6px}
figcaption{font-size:13px;color:var(--muted)}
.maps{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px}
svg.chart{width:100%;height:auto;margin:8px 0;font:12px system-ui,sans-serif}
.chart .label,.chart .value,.chart .dot-label,.chart .legend{fill:var(--fg)}
.chart .track{fill:var(--track)}.chart .bar.accent{fill:var(--accent)}
.chart .bar.good{fill:var(--good)}.chart .bar.ok{fill:var(--ok)}.chart .bar.bad{fill:var(--bad)}
.chart .bar.muted{fill:#9aa5b1}
.chart .band.bad{fill:#f4c7c1}.chart .band.ok{fill:#f7e3b5}.chart .band.good{fill:#cdebd8}
.chart .band.good2{fill:#a6dbbb}.chart .band-label,.chart .tick{fill:var(--fg);font-size:11px}
.chart .ref{stroke:var(--fg);stroke-dasharray:4 3}.chart .ref-label{fill:var(--fg);font-size:11px}
.chart .dot{fill:var(--accent)}
.chart .task0{fill:#dbe3ec}.chart .task1{fill:#c8d3df}
.chart .task-label{fill:#4a5663;font-size:10px}
.chart .mark{stroke:#fff;stroke-width:1}
.t0{fill:#c0392b}.t1{fill:#2f6fdb}.t2{fill:#b7791f}.t3{fill:#16703c}
.t4{fill:#8e44ad}.t5{fill:#16a0a0}.t6{fill:#d35400}.t7{fill:#5b6776}
footer{margin-top:50px;border-top:1px solid var(--line);padding-top:10px;font-size:13px;
color:var(--muted)}
@media print{body{font-size:12px}main{max-width:none;padding:0}nav.toc{display:none}
section{break-inside:auto}h2{break-after:avoid}figure,svg.chart,article.finding{break-inside:avoid}
.maps{grid-template-columns:1fr 1fr}@page{margin:14mm}}
"""
"""Hoja de estilo del informe: tema claro, legible al proyectar y al imprimir."""

TOC = (
    ("veredicto", "Lectura general"),
    ("sus", "SUS"),
    ("iuc", "IUC"),
    ("tareas", "Tareas"),
    ("hallazgos", "Hallazgos"),
    ("mapas", "Dónde pasó"),
    ("nielsen", "Nielsen"),
    ("limites", "Límites"),
)
"""Secciones del índice del informe."""


def render(inputs: ReportInputs) -> str:
    """Documento HTML completo del informe.

    Args:
        inputs: Datos ya reunidos.

    Returns:
        El HTML, autocontenido: sin recursos externos ni JavaScript.
    """
    toc = " ".join(f'<a href="#{anchor}">{_e(label)}</a>' for anchor, label in TOC)
    system = f" · {_e(inputs.system)}" if inputs.system else ""
    sections = [
        _verdict_section(inputs),
        _conclusions_section(inputs),
        _sus_section(inputs),
        _index_section(inputs),
        _tasks_section(inputs),
        _findings_section(inputs),
        _maps_section(inputs),
        _nielsen_section(inputs),
        _limits_section(inputs),
    ]
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Informe de usabilidad · {_e(inputs.study)}</title><style>{STYLE}</style></head>"
        '<body><main><header class="cover">'
        f'<h1>Informe de usabilidad</h1><div class="muted">{_e(inputs.study)}{system}</div>'
        f'<div class="muted small">Versiones: {_e(", ".join(inputs.versions))} · generado el '
        f"{_e(inputs.generated_at)}</div>"
        f'<nav class="toc" aria-label="Secciones">{toc}</nav></header>'
        + "".join(sections)
        + f"<footer>Generado por SUCA a partir de {_e(inputs.source)}. Contiene datos de "
        "participantes y capturas de la aplicación evaluada: consérvalo en local, no lo subas a "
        "servicios en línea.</footer></main></body></html>"
    )
