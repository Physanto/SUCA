"""Reúne de la base los datos del informe (``dashboard/report.py``).

Lee con ``DashboardData`` lo mismo que las páginas del panel (Hallazgos,
Pantallas, Índice, Tareas) y lo deja en un ``ReportInputs``: no escribe en la
base. Los mapas de calor se dibujan aquí, con el mismo código del panel, y se
incrustan como imágenes JPEG.

No importa Streamlit: la página del panel y ``scripts/study_report.py`` lo usan igual.
"""

import base64
import io
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image

from dashboard import findings, heatmap, replay
from dashboard.charts import incident_label
from dashboard.data import DashboardData
from dashboard.report import HeatmapFigure, ReportInputs
from dashboard.report_svg import TYPE_CLASSES, TimelineRow

MAX_SCREENS = 4
"""Pantallas con mapa de calor en el informe: las de los hallazgos más importantes."""

MAX_TIMELINES = 12
"""Sesiones en la línea de tiempo."""

MAP_WIDTH = 900
"""Ancho máximo de cada mapa de calor incrustado, en píxeles."""

MAP_LAYERS = ("click", "gaze")
"""Capas que se dibujan: el cursor se deja para el panel, por su cantidad de puntos."""


def collect(
    data: DashboardData,
    study_id: int,
    modes: Sequence[str],
    versions: Sequence[str] | None = None,
    *,
    source: str = "",
    generated_at: str | None = None,
    conclusions: str = "",
    max_screens: int = MAX_SCREENS,
) -> ReportInputs:
    """Datos del informe de un estudio.

    Args:
        data: Acceso de solo lectura a la base.
        study_id: Estudio.
        modes: Modos de sesión incluidos (por ejemplo, ``guided``).
        versions: Versiones incluidas; ``None`` para todas las de esos modos.
        source: Nombre de la base, para el pie del informe.
        generated_at: Fecha de generación; por defecto, la de ahora.
        conclusions: Conclusiones del evaluador.
        max_screens: Pantallas con mapa de calor.

    Returns:
        Los datos del informe. La gravedad y la recomendación de los hallazgos son
        las propuestas; quien las revisa reemplaza ``findings`` con
        ``dataclasses.replace``.

    Raises:
        LookupError: Si el estudio no existe o no tiene sesiones con esos filtros.
    """
    studies = data.get_studies()
    study = studies[studies["id"] == study_id]
    if study.empty:
        raise LookupError(f"study {study_id} does not exist")
    every = data.get_sessions(study_id=study_id)
    chosen = every[every["mode"].isin(modes)]
    if versions:
        chosen = chosen[chosen["version"].isin(versions)]
    if chosen.empty:
        raise LookupError(f"study {study_id} has no sessions with modes {list(modes)}")
    ids = set(chosen["session_id"])
    incidents = data.get_incidents(study_id=study_id)
    incidents = incidents[incidents["session_id"].isin(ids)].reset_index(drop=True)
    task_results = data.get_task_results(study_id)
    found = findings.build_findings(incidents, chosen, task_results).assign(recommendation="")
    index = data.get_usability_index(study_id)
    answers = data.get_sus_answers(study_id)
    legend, timelines = _timelines(data, chosen, incidents)
    return ReportInputs(
        study=str(study.iloc[0]["name"]),
        system=str(study.iloc[0]["system_under_test"] or ""),
        generated_at=generated_at or datetime.now().strftime("%d/%m/%Y %H:%M"),
        source=source,
        versions=sorted(chosen["version"].unique()),
        sessions=chosen,
        summary=findings.version_summary(chosen, task_results),
        tasks=findings.task_summary(task_results, incidents, chosen),
        findings=found,
        incidents=incidents,
        index=index[index["session_id"].isin(ids)].reset_index(drop=True),
        sus_answers=answers[answers["session_id"].isin(ids)].reset_index(drop=True),
        timelines=timelines,
        timeline_legend=legend,
        heatmaps=_heatmaps(data, study_id, chosen, found, max_screens),
        conclusions=conclusions,
    )


def _timelines(
    data: DashboardData, sessions: pd.DataFrame, incidents: pd.DataFrame
) -> tuple[list[str], list[TimelineRow]]:
    """Leyenda de tipos de incidente y una fila por sesión cerrada."""
    counts = incidents["type"].value_counts() if len(incidents) else pd.Series(dtype=int)
    kinds = list(counts.index[:TYPE_CLASSES])
    rows = []
    for session in sessions[sessions["ended_at"].notna()].head(MAX_TIMELINES).itertuples():
        tasks = data.get_session_tasks(int(session.session_id))
        # Se parte de la primera tarea: la calibración inicial, de más de un minuto, comprimiría
        # lo importante. Sin tareas (sesión libre) se parte del inicio de la sesión.
        start = float(tasks["t_start"].min()) if len(tasks) else float(session.started_at)
        own = incidents[incidents["session_id"] == session.session_id]
        rows.append(
            TimelineRow(
                label=f"{session.participant_id} · {session.version}",
                duration_ms=float(session.ended_at) - start,
                tasks=[
                    (float(row.t_start) - start, float(row.t_end) - start, f"T{int(row.position)}")
                    for row in tasks.itertuples()
                ],
                marks=[
                    (float(row.t) - start, kinds.index(row.type))
                    for row in own.itertuples()
                    if row.type in kinds and row.t >= start
                ],
            )
        )
    return [incident_label(kind) for kind in kinds], rows


def _heatmaps(
    data: DashboardData,
    study_id: int,
    sessions: pd.DataFrame,
    found: pd.DataFrame,
    max_screens: int,
) -> list[HeatmapFigure]:
    """Mapas de calor de clics y de mirada de las pantallas de los primeros hallazgos."""
    screens = [s for s in dict.fromkeys(found["screen"]) if s != "(sin pantalla)"][:max_screens]
    if not screens:
        return []
    captures = data.get_screen_captures(study_id)
    layers: dict[str, list[pd.DataFrame]] = {layer: [] for layer in MAP_LAYERS}
    viewport = heatmap.DEFAULT_VIEWPORT
    for session_id in sessions["session_id"]:
        session = data.get_session(int(session_id))
        viewport = replay.viewport_of(session)
        events = data.get_events(int(session_id))
        gaze = data.get_gaze(int(session_id))
        for layer in MAP_LAYERS:
            layers[layer].append(heatmap.points(events, gaze, layer))
    figures = []
    for screen in screens:
        shots = captures[[heatmap.screen_key(url) == screen for url in captures["url"]]]
        background = _open(shots.iloc[-1]["absolute_path"]) if not shots.empty else None
        for layer in MAP_LAYERS:
            joined = [frame for frame in layers[layer] if not frame.empty]
            points = pd.concat(joined, ignore_index=True) if joined else pd.DataFrame()
            chosen = (
                points[points["screen"] == screen][["x", "y"]].to_numpy() if len(points) else []
            )
            drawn = heatmap.render(chosen, layer=layer, background=background, viewport=viewport)
            if drawn.drawn == 0:
                continue
            caption = f"{len(sessions)} sesiones · {drawn.drawn} puntos"
            if drawn.outside:
                caption += f"; {drawn.outside} fuera de la imagen"
            caption += (
                "." if background is not None else ". Sin captura de esta pantalla: fondo neutro."
            )
            figures.append(
                HeatmapFigure(screen, heatmap.LAYERS[layer], _data_uri(drawn.image), caption)
            )
    return figures


def _open(path: str) -> Image.Image | None:
    """Abre una captura, o ``None`` si el archivo ya no está."""
    try:
        return Image.open(Path(path))
    except OSError:
        return None


def _data_uri(image: Image.Image) -> str:
    """Imagen reducida e incrustable como ``data:image/jpeg;base64,…``."""
    if image.width > MAP_WIDTH:
        image = image.resize((MAP_WIDTH, round(image.height * MAP_WIDTH / image.width)))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
