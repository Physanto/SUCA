"""Reproducción visual de una sesión y comprobación de la mirada con los clics.

La reproducción **no vuelve a ejecutar** la prueba: muestra las capturas que la
extensión tomó durante la sesión (la página real de ese momento, con lo escrito
en los campos que el estudio declara) y dibuja encima lo capturado: cursor,
clics, scroll, mirada, campos e incidentes, cada uno con su color, en el tiempo
en que pasó. Si la sesión no tiene capturas, usa la captura de referencia de
cada pantalla. Así se puede ver qué hizo la persona y dónde miraba, y comprobar
que la captura es coherente.

- ``build_payload`` arma los datos que necesita el reproductor, de toda la
  sesión o de un tramo (tiempos en ms desde el inicio del tramo y coordenadas de
  la ventana en píxeles CSS).
- ``task_windows`` da los tramos de cada tarea, para no cargar todas las
  capturas de una sesión larga.
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


#: Tipos de evento de campos que se dibujan, y la clase con que los ve el reproductor.
FIELD_EVENT_KINDS = {
    "focus_in": "focus",
    "focus_out": "blur",
    "field_change": "change",
    "validation_error": "error",
}


def _field_label(kind: str, data: Mapping[str, Any]) -> str | None:
    """Texto que acompaña a un evento de campo en el reproductor."""
    if kind == "field_change":
        if "text" in data:
            return f"«{data['text']}»"
        if "length" in data:
            deleted = data.get("deleted", 0)
            return f"{data['length']} caracteres" + (f" (borró {deleted})" if deleted else "")
        return "cambió"
    if kind == "validation_error":
        return f"error: {data.get('error_type', '')}".strip()
    return None


def _last_before_and_inside(rows: list[list[Any]], low: float, high: float) -> list[list[Any]]:
    """Filas ``[t, ...]`` dentro de ``[low, high]``, más la última anterior puesta en ``low``.

    Así el tramo empieza con la pantalla, el scroll o la captura que ya se veía.
    """
    before = [row for row in rows if row[0] < low]
    inside = [row for row in rows if low <= row[0] <= high]
    return ([[low, *before[-1][1:]]] if before else []) + inside


def build_payload(
    session: Mapping[str, Any],
    events: pd.DataFrame,
    gaze: pd.DataFrame,
    tasks: pd.DataFrame,
    incidents: pd.DataFrame,
    captures: pd.DataFrame,
    frames: pd.DataFrame | None = None,
    window: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Datos del reproductor para una sesión, o para un tramo de ella.

    Args:
        session: ``DashboardData.get_session``.
        events: ``DashboardData.get_events`` de la sesión.
        gaze: Mirada válida de la sesión (``DashboardData.get_gaze``).
        tasks: ``DashboardData.get_session_tasks``.
        incidents: ``DashboardData.get_incidents`` de la sesión.
        captures: ``DashboardData.get_screen_captures`` del estudio (fondo de
            respaldo cuando no hay captura de la sesión).
        frames: ``DashboardData.get_session_frames``: lo que se veía en cada
            momento. Si falta, se dibuja sobre las capturas de referencia.
        window: Tramo a reproducir (inicio y fin, en ms con el reloj de la
            sesión). Si falta, toda la sesión.

    Returns:
        Diccionario serializable en JSON, con tiempos en ms desde el inicio del
        tramo: ``duration``, ``viewport``, ``screens`` (cambios de pantalla),
        ``scrolls``, ``moves`` (posiciones del cursor), ``clicks``, ``gaze``,
        ``fields`` (foco, cambios y errores de campos, con su caja y su texto),
        ``tasks``, ``incidents``, ``frames`` (``[t, índice]`` en ``frame_images``),
        ``frame_images`` e ``images`` (captura de referencia de cada pantalla).
    """
    start = float(session["started_at"])
    last = [float(session["ended_at"] or start)]
    for table in (events, gaze):
        if not table.empty:
            last.append(float(table["t"].max()))
    low, high = window if window is not None else (start, max(last))
    viewport = viewport_of(session)

    def rows(kind: str) -> pd.DataFrame:
        return events[events["type"] == kind] if not events.empty else events

    def relative(items: list[list[Any]]) -> list[list[Any]]:
        return [[_ms(item[0], low), *item[1:]] for item in items]

    def inside(t: float) -> bool:
        return low <= t <= high

    screen_rows = [
        [float(row.t), row.url, row.title, screen_key(row.url)]
        for row in rows("screen_change").itertuples()
    ]
    screens = [
        {"t": t, "url": url, "title": title, "screen": screen}
        for t, url, title, screen in relative(_last_before_and_inside(screen_rows, low, high))
    ]
    # Cada cambio de pantalla vuelve el scroll arriba; después, cada evento scroll lo mueve.
    scroll_rows = [[row[0], 0.0, 0.0] for row in screen_rows]
    for row in rows("scroll").itertuples():
        data = row.data if isinstance(row.data, dict) else {}
        scroll_rows.append(
            [float(row.t), float(data.get("scroll_x", 0)), float(data.get("scroll_y", 0))]
        )
    scroll_rows.sort(key=lambda item: item[0])
    pointer = (
        events[events["type"].isin(["mousemove", "click"]) & events["x"].notna()]
        if not events.empty
        else events
    )
    move_rows = [[float(row.t), round(row.x, 1), round(row.y, 1)] for row in pointer.itertuples()]
    clicks = [
        [_ms(row.t, low), round(row.x, 1), round(row.y, 1)]
        for row in rows("click").itertuples()
        if not pd.isna(row.x) and inside(row.t)
    ]
    valid = gaze[gaze["x"].notna()] if not gaze.empty else gaze
    gaze_points = [
        [_ms(row.t, low), round(row.x, 1), round(row.y, 1)]
        for row in valid.itertuples()
        if inside(row.t)
    ]
    fields = []
    field_events = events[events["type"].isin(FIELD_EVENT_KINDS)] if not events.empty else events
    for row in field_events.itertuples():
        if not inside(row.t):
            continue
        element = row.element if isinstance(row.element, dict) else {}
        data = row.data if isinstance(row.data, dict) else {}
        box = element.get("box")
        fields.append(
            {
                "t": _ms(row.t, low),
                "kind": FIELD_EVENT_KINDS[row.type],
                "box": [box["x"], box["y"], box["w"], box["h"]] if box else None,
                "label": _field_label(row.type, data),
            }
        )
    task_bands = [
        {
            "from": _ms(max(row.t_start, low), low),
            "to": _ms(min(row.t_end, high), low),
            "label": f"Tarea {row.position}",
            "instruction": row.instruction,
        }
        for row in tasks.itertuples()
        if row.t_end >= low and row.t_start <= high
    ]
    incident_marks = [
        {"t": _ms(row.t, low), "label": incident_label(row.type), "screen": row.screen}
        for row in incidents.itertuples()
        if inside(row.t)
    ]
    images: dict[str, str] = {}
    for row in captures.sort_values("t").itertuples():
        url = _image_url(row.absolute_path, viewport[0])
        if url is not None:
            # La más reciente de cada pantalla reemplaza a las anteriores.
            images[screen_key(row.url)] = url
    frame_rows = (
        [[float(row.t), row.absolute_path] for row in frames.itertuples()]
        if frames is not None and not frames.empty
        else []
    )
    frame_marks: list[list[int]] = []
    frame_images: list[str] = []
    for t, path in _last_before_and_inside(frame_rows, low, high):
        url = _image_url(path, viewport[0])
        if url is not None:
            frame_marks.append([_ms(t, low), len(frame_images)])
            frame_images.append(url)
    return {
        "duration": _ms(high, low),
        "viewport": list(viewport),
        "screens": screens,
        "scrolls": relative(_last_before_and_inside(scroll_rows, low, high)),
        "moves": relative(_last_before_and_inside(move_rows, low, high)),
        "clicks": clicks,
        "gaze": gaze_points,
        "fields": fields,
        "tasks": task_bands,
        "incidents": incident_marks,
        "frames": frame_marks,
        "frame_images": frame_images,
        "images": images,
    }


#: Margen antes y después de una tarea al reproducirla, para ver cómo empieza y termina.
TASK_MARGIN_MS = 2000


def task_windows(tasks: pd.DataFrame) -> list[tuple[str, tuple[float, float]]]:
    """Tramos de la sesión que se pueden reproducir por separado: uno por tarea.

    Args:
        tasks: ``DashboardData.get_session_tasks``.

    Returns:
        Pares ``(nombre, (inicio, fin))`` en orden, con ``TASK_MARGIN_MS`` a cada lado.
    """
    return [
        (
            f"Tarea {row.position}: {row.instruction}",
            (float(row.t_start) - TASK_MARGIN_MS, float(row.t_end) + TASK_MARGIN_MS),
        )
        for row in tasks.sort_values("position").itertuples()
    ]


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
