"""Reproducción visual de una sesión y comprobación de la mirada con los clics.

La reproducción **no vuelve a ejecutar** la prueba: dibuja lo capturado
(cursor, clics, scroll y mirada) sobre la captura de cada pantalla, en el
tiempo en que pasó. Así se puede ver qué hizo la persona y dónde miraba, y
comprobar que la captura es coherente.

- ``build_payload`` arma los datos que necesita el reproductor (tiempos en ms
  desde el inicio de la sesión y coordenadas de la ventana en píxeles CSS).
- ``player_html`` devuelve la página del reproductor con esos datos adentro;
  la página la muestra con ``st.iframe``.
- ``gaze_at_clicks`` mide, en cada clic, qué tan lejos estaba la mirada del
  punto del clic: casi siempre se mira lo que se pulsa, así que una distancia
  chica indica que la mirada funciona.

No importa Streamlit.
"""

import base64
import io
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from dashboard.charts import incident_label
from dashboard.heatmap import DEFAULT_VIEWPORT, screen_key

#: Página del reproductor; los datos reemplazan a ``PAYLOAD_MARK``.
PLAYER_TEMPLATE = Path(__file__).with_name("replay-player.html")
PAYLOAD_MARK = "/*PAYLOAD*/null"

#: Tramo de mirada que se compara con cada clic: desde antes del clic hasta un poco después.
CLICK_GAZE_BEFORE_MS = 500
CLICK_GAZE_AFTER_MS = 100

#: Distancia entre mirada y clic que se considera "mirando lo que pulsa", en píxeles CSS.
NEAR_CLICK_PX = 100

#: Calidad de las capturas dentro del reproductor (JPEG), para que la página no pese de más.
IMAGE_QUALITY = 75


def viewport_of(session: Mapping[str, Any] | None) -> tuple[int, int]:
    """Tamaño de la ventana de una sesión, en píxeles CSS.

    Args:
        session: ``DashboardData.get_session``.

    Returns:
        Ancho y alto de la ventana (o ``DEFAULT_VIEWPORT`` si no se informó).
    """
    info = (session or {}).get("screen_info") or {}
    width, height = info.get("window_width"), info.get("window_height")
    if not width or not height:
        return DEFAULT_VIEWPORT
    return int(width), int(height)


def _ms(value: float, start: float) -> int:
    """Milisegundos desde el inicio, enteros."""
    return int(round(float(value) - start))


def _image_url(path: str, width: int) -> str | None:
    """La captura como data URL JPEG, al ancho de la ventana; ``None`` si no se puede leer."""
    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
    except OSError:
        return None
    height = max(1, round(rgb.height * width / rgb.width))
    buffer = io.BytesIO()
    rgb.resize((width, height)).save(buffer, format="JPEG", quality=IMAGE_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build_payload(
    session: Mapping[str, Any],
    events: pd.DataFrame,
    gaze: pd.DataFrame,
    tasks: pd.DataFrame,
    incidents: pd.DataFrame,
    captures: pd.DataFrame,
) -> dict[str, Any]:
    """Datos del reproductor para una sesión.

    Args:
        session: ``DashboardData.get_session``.
        events: ``DashboardData.get_events`` de la sesión.
        gaze: Mirada válida de la sesión (``DashboardData.get_gaze``).
        tasks: ``DashboardData.get_session_tasks``.
        incidents: ``DashboardData.get_incidents`` de la sesión.
        captures: ``DashboardData.get_screen_captures`` del estudio.

    Returns:
        Diccionario serializable en JSON: ``duration``, ``viewport``, ``screens``
        (cambios de pantalla), ``scrolls``, ``moves`` (posiciones del cursor),
        ``clicks``, ``gaze``, ``tasks``, ``incidents`` e ``images`` (captura de
        cada pantalla normalizada que la tenga).
    """
    start = float(session["started_at"])
    last = [float(session["ended_at"] or start)]
    for frame in (events, gaze):
        if not frame.empty:
            last.append(float(frame["t"].max()))
    viewport = viewport_of(session)

    def rows(kind: str) -> pd.DataFrame:
        return events[events["type"] == kind] if not events.empty else events

    screens = [
        {"t": _ms(row.t, start), "url": row.url, "title": row.title, "screen": screen_key(row.url)}
        for row in rows("screen_change").itertuples()
    ]
    # Cada cambio de pantalla vuelve el scroll arriba; después, cada evento scroll lo mueve.
    scrolls = [[screen["t"], 0.0, 0.0] for screen in screens]
    for row in rows("scroll").itertuples():
        data = row.data if isinstance(row.data, dict) else {}
        scrolls.append(
            [_ms(row.t, start), float(data.get("scroll_x", 0)), float(data.get("scroll_y", 0))]
        )
    scrolls.sort(key=lambda item: item[0])
    pointer = (
        events[events["type"].isin(["mousemove", "click"]) & events["x"].notna()]
        if not events.empty
        else events
    )
    moves = [[_ms(row.t, start), round(row.x, 1), round(row.y, 1)] for row in pointer.itertuples()]
    clicks = [
        [_ms(row.t, start), round(row.x, 1), round(row.y, 1)]
        for row in rows("click").itertuples()
        if not pd.isna(row.x)
    ]
    valid = gaze[gaze["x"].notna()] if not gaze.empty else gaze
    gaze_points = [
        [_ms(row.t, start), round(row.x, 1), round(row.y, 1)] for row in valid.itertuples()
    ]
    task_bands = [
        {
            "from": _ms(row.t_start, start),
            "to": _ms(row.t_end, start),
            "label": f"Tarea {row.position}",
            "instruction": row.instruction,
        }
        for row in tasks.itertuples()
    ]
    incident_marks = [
        {"t": _ms(row.t, start), "label": incident_label(row.type), "screen": row.screen}
        for row in incidents.itertuples()
    ]
    images: dict[str, str] = {}
    for row in captures.sort_values("t").itertuples():
        url = _image_url(row.absolute_path, viewport[0])
        if url is not None:
            # La más reciente de cada pantalla reemplaza a las anteriores.
            images[screen_key(row.url)] = url
    return {
        "duration": _ms(max(last), start),
        "viewport": list(viewport),
        "screens": screens,
        "scrolls": scrolls,
        "moves": moves,
        "clicks": clicks,
        "gaze": gaze_points,
        "tasks": task_bands,
        "incidents": incident_marks,
        "images": images,
    }


def player_html(payload: Mapping[str, Any]) -> str:
    """Página del reproductor con los datos de la sesión.

    Args:
        payload: Resultado de ``build_payload``.

    Returns:
        Documento HTML completo, sin recursos externos.
    """
    template = PLAYER_TEMPLATE.read_text(encoding="utf-8")
    # `</` dentro de un <script> cerraría la etiqueta antes de tiempo.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return template.replace(PAYLOAD_MARK, data)


def gaze_at_clicks(events: pd.DataFrame, gaze: pd.DataFrame) -> pd.DataFrame:
    """Distancia entre la mirada y cada clic.

    Para cada clic se toma la mirada válida desde ``CLICK_GAZE_BEFORE_MS`` antes
    hasta ``CLICK_GAZE_AFTER_MS`` después, y se usa su mediana (la mirada es
    ruidosa). Las dos posiciones están en coordenadas de la ventana.

    Args:
        events: ``DashboardData.get_events`` de la sesión.
        gaze: Mirada válida de la sesión.

    Returns:
        Un clic por fila: ``t``, ``x``, ``y``, ``gaze_x``, ``gaze_y`` y
        ``distance_px``. Los clics sin mirada en ese tramo no aparecen.
    """
    columns = ["t", "x", "y", "gaze_x", "gaze_y", "distance_px"]
    if events.empty or gaze.empty:
        return pd.DataFrame(columns=columns)
    clicks = events[(events["type"] == "click") & events["x"].notna()]
    valid = gaze[gaze["x"].notna()].sort_values("t")
    times = valid["t"].to_numpy(dtype=float)
    xs, ys = valid["x"].to_numpy(dtype=float), valid["y"].to_numpy(dtype=float)
    rows = []
    for click in clicks.itertuples():
        low = np.searchsorted(times, click.t - CLICK_GAZE_BEFORE_MS, side="left")
        high = np.searchsorted(times, click.t + CLICK_GAZE_AFTER_MS, side="right")
        if high <= low:
            continue
        gaze_x, gaze_y = float(np.median(xs[low:high])), float(np.median(ys[low:high]))
        rows.append(
            [
                click.t,
                click.x,
                click.y,
                gaze_x,
                gaze_y,
                math.hypot(gaze_x - click.x, gaze_y - click.y),
            ]
        )
    return pd.DataFrame(rows, columns=columns)


def agreement_summary(distances: pd.DataFrame, clicks: int) -> dict[str, Any]:
    """Resumen de ``gaze_at_clicks``.

    Args:
        distances: Resultado de ``gaze_at_clicks``.
        clicks: Total de clics de la sesión.

    Returns:
        ``clicks``, ``with_gaze`` (clics con mirada cerca en el tiempo),
        ``median_px`` y ``near_share`` (fracción a menos de ``NEAR_CLICK_PX``);
        estos dos, ``None`` si no hay clics con mirada.
    """
    if distances.empty:
        return {"clicks": clicks, "with_gaze": 0, "median_px": None, "near_share": None}
    values = distances["distance_px"].astype(float)
    return {
        "clicks": clicks,
        "with_gaze": len(values),
        "median_px": float(values.median()),
        "near_share": float((values <= NEAR_CLICK_PX).mean()),
    }
