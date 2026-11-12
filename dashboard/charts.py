"""Gráficas del panel de resultados, con Altair.

Cada función recibe DataFrames de ``dashboard.data`` y devuelve un gráfico listo
para ``st.altair_chart``. Los tiempos de una sesión se muestran en segundos
desde su inicio. No importa Streamlit, para poder probarlas.
"""

from collections.abc import Mapping

import altair as alt
import pandas as pd

from dashboard.heatmap import screen_key
from dashboard.heatmap_insights import COLUMNS, ROWS

#: Etiquetas en español de los tipos de incidente (``incident_type``).
INCIDENT_LABELS: Mapping[str, str] = {
    "rage_click": "Clics de frustración",
    "dead_click": "Clic sin respuesta",
    "hesitation": "Vacilación",
    "long_pause": "Pausa larga",
    "navigation_loop": "Navegación en círculo",
    "repeated_search": "Búsqueda repetida",
    "form_error": "Error de formulario",
    "field_reentry": "Campo corregido",
    "form_abandonment": "Formulario abandonado",
    "task_overtime": "Tarea demasiado larga",
}

#: Etiquetas de los tipos de episodio (``episode_type``).
EPISODE_LABELS: Mapping[str, str] = {
    "screen": "Pantalla",
    "form": "Formulario",
    "search": "Búsqueda",
    "login": "Inicio de sesión",
}

#: Señales faciales que se grafican: promedio de los dos lados de cada una.
FACE_SIGNALS: Mapping[str, tuple[str, ...]] = {
    "Ceño fruncido": ("brow_down_left", "brow_down_right"),
    "Labios apretados": ("mouth_press_left", "mouth_press_right"),
    "Sonrisa": ("mouth_smile_left", "mouth_smile_right"),
}

#: Carriles de la línea de tiempo, de arriba abajo.
LANES = ("Tareas", "Pantallas", "Episodios", "Incidentes", "Clics")


def incident_label(kind: str) -> str:
    """Etiqueta en español de un tipo de incidente (el tipo mismo si no se conoce)."""
    return INCIDENT_LABELS.get(kind, kind)


def _seconds(values: pd.Series, start: float) -> pd.Series:
    """Segundos desde el inicio de la sesión."""
    return (pd.to_numeric(values) - start) / 1000


def timeline(
    start: float,
    tasks: pd.DataFrame,
    episodes: pd.DataFrame,
    incidents: pd.DataFrame,
    events: pd.DataFrame,
) -> alt.LayerChart:
    """Línea de tiempo de una sesión: tareas, pantallas, episodios, incidentes y clics.

    Args:
        start: Inicio de la sesión (ms desde 1970).
        tasks: ``DashboardData.get_session_tasks``.
        episodes: ``DashboardData.get_episodes``.
        incidents: ``DashboardData.get_incidents`` de la sesión.
        events: ``DashboardData.get_events`` de la sesión.

    Returns:
        Gráfico con un carril por tipo de dato y el tiempo en segundos.
    """
    bars = []
    for row in tasks.itertuples():
        bars.append(
            {
                "lane": "Tareas",
                "from": row.t_start,
                "to": row.t_end,
                "label": f"Tarea {row.position}",
                "short": f"T{row.position}",
                "detail": f"Terminó por: {row.ended_by}",
            }
        )
    for row in episodes.itertuples():
        bars.append(
            {
                "lane": "Pantallas" if row.type == "screen" else "Episodios",
                "from": row.t_start,
                "to": row.t_end,
                "label": row.screen
                if row.type == "screen"
                else EPISODE_LABELS.get(row.type, row.type),
                "detail": f"{EPISODE_LABELS.get(row.type, row.type)} · {row.outcome or ''}",
            }
        )
    bar_frame = pd.DataFrame(bars, columns=["lane", "from", "to", "label", "short", "detail"])
    bar_frame["from"] = _seconds(bar_frame["from"], start)
    bar_frame["to"] = _seconds(bar_frame["to"], start)

    marks = [
        {"lane": "Incidentes", "at": row.t, "label": incident_label(row.type), "detail": row.screen}
        for row in incidents.itertuples()
    ]
    clicks = events[events["type"] == "click"] if not events.empty else events
    marks += [
        {"lane": "Clics", "at": row.t, "label": "Clic", "detail": screen_key(row.url)}
        for row in clicks.itertuples()
    ]
    mark_frame = pd.DataFrame(marks, columns=["lane", "at", "label", "detail"])
    mark_frame["at"] = _seconds(mark_frame["at"], start)

    lane = alt.Y("lane:N", title=None, sort=list(LANES), scale=alt.Scale(domain=list(LANES)))
    time = alt.Scale(zero=False)
    bars_chart = (
        alt.Chart(bar_frame)
        .mark_bar(height=16, cornerRadius=3)
        .encode(
            x=alt.X("from:Q", title="Segundos desde el inicio", scale=time),
            x2="to:Q",
            y=lane,
            color=alt.Color("label:N", legend=None),
            tooltip=[
                alt.Tooltip("label:N", title="Qué"),
                alt.Tooltip("detail:N", title="Detalle"),
                alt.Tooltip("from:Q", title="Desde (s)", format=".1f"),
                alt.Tooltip("to:Q", title="Hasta (s)", format=".1f"),
            ],
        )
    )
    marks_chart = (
        alt.Chart(mark_frame)
        .mark_point(filled=True, size=70)
        .encode(
            x=alt.X("at:Q", scale=time),
            y=lane,
            color=alt.Color("label:N", legend=alt.Legend(title="Marcas", orient="bottom")),
            shape=alt.Shape("lane:N", legend=None),
            tooltip=[
                alt.Tooltip("label:N", title="Qué"),
                alt.Tooltip("detail:N", title="Pantalla"),
                alt.Tooltip("at:Q", title="Segundo", format=".1f"),
            ],
        )
    )
    task_labels = (
        alt.Chart(
            bar_frame[bar_frame["lane"] == "Tareas"].assign(
                middle=lambda f: (f["from"] + f["to"]) / 2
            )
        )
        .mark_text(color="white", fontWeight="bold", fontSize=11)
        .encode(x=alt.X("middle:Q", scale=time), y=lane, text="short:N")
    )
    return (
        alt.layer(bars_chart, task_labels, marks_chart)
        .properties(height=230)
        .interactive(bind_y=False)
    )


FACE_MAX_POINTS = 1500
"""Puntos máximos por señal facial: Altair rechaza más de 5000 filas por gráfica."""


def face_signals(start: float, face: pd.DataFrame, window_s: float = 1.0) -> alt.Chart:
    """Señales faciales de una sesión, suavizadas con una media móvil.

    Después de suavizar, la señal se promedia por tramos para no pasar de
    ``FACE_MAX_POINTS`` puntos: a 15 muestras por segundo una sesión de diez
    minutos tiene 9000 por señal.

    Args:
        start: Inicio de la sesión (ms desde 1970).
        face: ``DashboardData.get_face``.
        window_s: Ancho de la media móvil, en segundos.

    Returns:
        Una línea por señal de ``FACE_SIGNALS``, entre 0 y 1.
    """
    rows = []
    detected = face[face["face_detected"].fillna(False).astype(bool)] if not face.empty else face
    for name, keys in FACE_SIGNALS.items():
        values = [
            sum(float(item.get(key, 0)) for key in keys) / len(keys)
            if isinstance(item, dict)
            else None
            for item in detected["values"]
        ]
        series = pd.Series(values, index=pd.to_datetime(detected["t"], unit="ms"), dtype=float)
        smooth = series.rolling(f"{int(window_s * 1000)}ms").mean()
        seconds = _seconds(detected["t"], start).to_numpy()
        span = float(seconds.max() - seconds.min()) if len(seconds) else 0.0
        # Tramos de al menos un cuarto de la media móvil: no se pierde lo que ella deja ver.
        step = max(window_s / 4, span / FACE_MAX_POINTS)
        points = pd.DataFrame({"second": seconds, "value": smooth.to_numpy()})
        points = points.groupby((points["second"] // step) if step > 0 else points.index).mean()
        rows.append(points.assign(signal=name))
    frame = (
        pd.concat(rows, ignore_index=True)
        if rows
        else pd.DataFrame(columns=["second", "value", "signal"])
    )
    return (
        alt.Chart(frame)
        .mark_line(strokeWidth=1.5)
        .encode(
            x=alt.X("second:Q", title="Segundos desde el inicio", scale=alt.Scale(zero=False)),
            y=alt.Y("value:Q", title="Intensidad", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("signal:N", title="Señal", legend=alt.Legend(orient="bottom")),
            tooltip=[alt.Tooltip("signal:N", title="Señal"), alt.Tooltip("value:Q", format=".2f")],
        )
        .properties(height=180)
        .interactive(bind_y=False)
    )


def incidents_by_screen(incidents: pd.DataFrame) -> alt.Chart:
    """Incidentes por pantalla, apilados por tipo.

    Args:
        incidents: ``DashboardData.get_incidents`` de un estudio.

    Returns:
        Barras horizontales, de la pantalla con más incidentes a la de menos.
    """
    frame = incidents.dropna(subset=["screen"]).copy()
    frame["kind"] = frame["type"].map(incident_label)
    order = frame["screen"].value_counts().index.tolist()
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            y=alt.Y("screen:N", title=None, sort=order),
            x=alt.X("count():Q", title="Incidentes"),
            color=alt.Color("kind:N", title="Tipo", legend=alt.Legend(orient="bottom", columns=3)),
            tooltip=[
                alt.Tooltip("screen:N", title="Pantalla"),
                alt.Tooltip("kind:N", title="Tipo"),
                alt.Tooltip("count():Q", title="Incidentes"),
            ],
        )
        .properties(height=max(120, 28 * len(order)))
    )


def time_by_screen(screens: pd.DataFrame) -> alt.Chart:
    """Tiempo total en cada pantalla del estudio.

    Args:
        screens: ``DashboardData.get_screen_summary``.

    Returns:
        Barras horizontales del tiempo, en segundos.
    """
    frame = screens.copy()
    frame["seconds"] = pd.to_numeric(frame["time_ms"]) / 1000
    return (
        alt.Chart(frame)
        .mark_bar(color="#4c78a8")
        .encode(
            y=alt.Y("screen:N", title=None, sort="-x"),
            x=alt.X("seconds:Q", title="Tiempo total (s)"),
            tooltip=[
                alt.Tooltip("screen:N", title="Pantalla"),
                alt.Tooltip("seconds:Q", title="Tiempo (s)", format=".1f"),
                alt.Tooltip("visits:Q", title="Visitas"),
                alt.Tooltip("sessions:Q", title="Sesiones"),
            ],
        )
        .properties(height=max(120, 28 * len(frame)))
    )


def task_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Resumen por tarea y versión: éxito, tiempos, pasos y desvío más frecuente.

    Args:
        results: ``DashboardData.get_task_results``.

    Returns:
        ``position``, ``instruction``, ``version``, ``sessions``, ``success_rate``
        (entre 0 y 1, sin contar las que no se pudieron juzgar), ``median_duration_ms``,
        ``median_steps`` y ``frequent_deviation`` (el paso de desvío más común).
    """
    rows = []
    for (position, instruction, version), group in results.groupby(
        ["position", "instruction", "version"], sort=True
    ):
        judged = group["success"].dropna()
        deviations = group["deviation_step"].dropna()
        rows.append(
            {
                "position": position,
                "instruction": instruction,
                "version": version,
                "sessions": len(group),
                "success_rate": float(judged.astype(bool).mean()) if len(judged) else None,
                "median_duration_ms": float(pd.to_numeric(group["duration_ms"]).median()),
                "median_steps": float(pd.to_numeric(group["steps"]).median()),
                "frequent_deviation": int(deviations.mode().iloc[0]) if len(deviations) else None,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "position", "instruction", "version", "sessions", "success_rate",
            "median_duration_ms", "median_steps", "frequent_deviation",
        ],
    )  # fmt: skip


def task_success(summary: pd.DataFrame) -> alt.Chart:
    """Tasa de éxito de cada tarea, por versión.

    Args:
        summary: ``task_summary``.

    Returns:
        Barras agrupadas por tarea, una por versión.
    """
    frame = summary.copy()
    frame["task"] = "Tarea " + frame["position"].astype(str)
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("task:N", title=None),
            xOffset="version:N",
            y=alt.Y(
                "success_rate:Q",
                title="Éxito",
                axis=alt.Axis(format="%"),
                scale=alt.Scale(domain=[0, 1]),
            ),
            color=alt.Color("version:N", title="Versión"),
            tooltip=[
                alt.Tooltip("task:N", title="Tarea"),
                alt.Tooltip("version:N", title="Versión"),
                alt.Tooltip("success_rate:Q", title="Éxito", format=".0%"),
                alt.Tooltip("sessions:Q", title="Sesiones"),
            ],
        )
        .properties(height=240)
    )


def task_durations(results: pd.DataFrame) -> alt.Chart:
    """Duración de cada tarea en cada sesión, por versión.

    Args:
        results: ``DashboardData.get_task_results``.

    Returns:
        Un punto por sesión y tarea, agrupados por versión.
    """
    frame = results.copy()
    frame["task"] = "Tarea " + frame["position"].astype(str)
    frame["seconds"] = pd.to_numeric(frame["duration_ms"]) / 1000
    return (
        alt.Chart(frame)
        .mark_circle(size=80, opacity=0.8)
        .encode(
            x=alt.X("task:N", title=None),
            xOffset="version:N",
            y=alt.Y("seconds:Q", title="Duración (s)"),
            color=alt.Color("version:N", title="Versión"),
            tooltip=[
                alt.Tooltip("participant_id:N", title="Participante"),
                alt.Tooltip("version:N", title="Versión"),
                alt.Tooltip("seconds:Q", title="Duración (s)", format=".1f"),
                alt.Tooltip("success:N", title="Éxito"),
            ],
        )
        .properties(height=240)
    )


#: Componentes del índice y su etiqueta.
INDEX_COMPONENTS: Mapping[str, str] = {
    "effectiveness": "Efectividad",
    "time_efficiency": "Eficiencia temporal",
    "path_efficiency": "Eficiencia de ruta",
    "friction": "Fricción",
}


def index_components(index: pd.DataFrame) -> alt.Chart:
    """Componentes del índice por versión (media de las sesiones).

    Args:
        index: ``DashboardData.get_usability_index``.

    Returns:
        Barras agrupadas por componente, una por versión.
    """
    long = index.melt(
        id_vars=["session_id", "version"],
        value_vars=list(INDEX_COMPONENTS),
        var_name="component",
        value_name="value",
    )
    long["component"] = long["component"].map(INDEX_COMPONENTS)
    return (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("component:N", title=None, sort=list(INDEX_COMPONENTS.values())),
            xOffset="version:N",
            y=alt.Y("mean(value):Q", title="Valor medio", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("version:N", title="Versión"),
            tooltip=[
                alt.Tooltip("component:N", title="Componente"),
                alt.Tooltip("version:N", title="Versión"),
                alt.Tooltip("mean(value):Q", title="Media", format=".2f"),
            ],
        )
        .properties(height=240)
    )


def correlation(index: pd.DataFrame) -> tuple[float | None, int]:
    """Correlación de Spearman entre el IUC y el SUS de las sesiones que tienen los dos.

    Args:
        index: ``DashboardData.get_usability_index``.

    Returns:
        El coeficiente (``None`` con menos de 3 sesiones o sin variación) y cuántas
        sesiones entraron.
    """
    both = index[["bui", "sus_score"]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(both) < 3 or both["bui"].nunique() < 2 or both["sus_score"].nunique() < 2:
        return None, len(both)
    # Spearman es la correlación de Pearson de los rangos (sin depender de SciPy).
    ranks = both.rank()
    return float(ranks["bui"].corr(ranks["sus_score"])), len(both)


def bui_vs_sus(index: pd.DataFrame) -> alt.Chart:
    """IUC frente a SUS, una sesión por punto.

    Args:
        index: ``DashboardData.get_usability_index``.

    Returns:
        Dispersión con el IUC (0 a 100) en x y el SUS (0 a 100) en y.
    """
    frame = index.dropna(subset=["bui", "sus_score"])
    return (
        alt.Chart(frame)
        .mark_circle(size=120, opacity=0.85)
        .encode(
            x=alt.X("bui:Q", title="IUC", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("sus_score:Q", title="SUS", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("version:N", title="Versión"),
            tooltip=[
                alt.Tooltip("participant_id:N", title="Participante"),
                alt.Tooltip("version:N", title="Versión"),
                alt.Tooltip("bui:Q", title="IUC", format=".1f"),
                alt.Tooltip("sus_score:Q", title="SUS", format=".1f"),
            ],
        )
        .properties(height=300)
    )


def zone_grid(shares: pd.DataFrame, what: str) -> alt.Chart:
    """Reparto de un mapa de calor por zonas de la pantalla, como una cuadrícula.

    Args:
        shares: ``heatmap_insights.zone_shares``.
        what: Qué se cuenta, para el título de la leyenda (por ejemplo, "clics").

    Returns:
        Cuadrícula de 4 × 3 (tres filas de la primera vista y lo que quedó
        debajo), con el porcentaje escrito en cada celda.
    """
    top = max(0.01, float(shares["share"].max()))
    base = alt.Chart(shares).encode(
        x=alt.X("column:N", title=None, sort=list(COLUMNS), axis=alt.Axis(orient="top")),
        y=alt.Y("row:N", title=None, sort=list(ROWS)),
    )
    cells = base.mark_rect(stroke="white").encode(
        color=alt.Color(
            "share:Q",
            title=f"% de {what}",
            scale=alt.Scale(scheme="orangered", domain=[0, top]),
            legend=alt.Legend(format=".0%"),
        ),
        tooltip=[
            alt.Tooltip("row:N", title="Fila"),
            alt.Tooltip("column:N", title="Columna"),
            alt.Tooltip("count:Q", title=what.capitalize()),
            alt.Tooltip("share:Q", title="Parte", format=".0%"),
        ],
    )
    labels = base.mark_text(fontSize=13).encode(
        text=alt.Text("share:Q", format=".0%"),
        color=alt.condition(alt.datum.share > 0.25, alt.value("white"), alt.value("#1f2328")),
    )
    return (cells + labels).properties(height=200)


def top_elements(frame: pd.DataFrame, value: str, title: str, *, fmt: str = "d") -> alt.Chart:
    """Barras de los elementos con más clics o más tiempo de mirada.

    Args:
        frame: Una fila por elemento con ``label``, la columna ``value`` y, si se
            conoce, ``interactive`` (vacío en sin asignar).
        value: Columna que se grafica.
        title: Título del eje.
        fmt: Formato del valor en la etiqueta emergente.

    Returns:
        Barras horizontales, de mayor a menor, coloreadas según el tipo de elemento.
    """
    data = frame.copy()
    data["kind"] = [
        "Sin asignar"
        if pd.isna(interactive)
        else ("Interactivo" if bool(interactive) else "No interactivo")
        for interactive in data["interactive"]
    ]
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            y=alt.Y("label:N", title=None, sort=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X(f"{value}:Q", title=title),
            color=alt.Color(
                "kind:N",
                title="Elemento",
                scale=alt.Scale(
                    domain=["Interactivo", "No interactivo", "Sin asignar"],
                    range=["#4c78a8", "#f58518", "#9aa1a9"],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("label:N", title="Elemento"),
                alt.Tooltip(f"{value}:Q", title=title, format=fmt),
                alt.Tooltip("kind:N", title="Tipo"),
            ],
        )
        .properties(height=max(120, 26 * len(data)))
    )


def gaze_states(shares: pd.DataFrame) -> alt.Chart:
    """Parte del tiempo en cada estado de la mirada.

    Args:
        shares: ``heatmap_insights.gaze_state_shares``.

    Returns:
        Barras horizontales con el porcentaje de cada estado.
    """
    return (
        alt.Chart(shares)
        .mark_bar(color="#54a24b")
        .encode(
            y=alt.Y("state:N", title=None, sort="-x"),
            x=alt.X("share:Q", title="Parte del tiempo", axis=alt.Axis(format=".0%")),
            tooltip=[
                alt.Tooltip("state:N", title="Estado"),
                alt.Tooltip("share:Q", title="Parte", format=".1%"),
            ],
        )
        .properties(height=max(100, 26 * len(shares)))
    )
