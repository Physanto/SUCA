"""Mapas de calor de clics, cursor y mirada sobre una pantalla.

Las posiciones se llevan a **coordenadas de la página** (las de la ventana más
el scroll de ese momento), para que coincidan con la captura de la pantalla
aunque la persona haya bajado. La captura de referencia muestra lo que se veía
en la ventana al tomarla (normalmente, arriba de todo): lo que quedó más abajo
se cuenta, pero no se dibuja sobre ella.

Sin captura, el mapa se dibuja sobre un fondo neutro del tamaño de la ventana.

No importa Streamlit: las páginas reciben una imagen de Pillow.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

LAYERS: dict[str, str] = {"click": "Clics", "cursor": "Cursor", "gaze": "Mirada"}
"""Capas que se pueden dibujar y su etiqueta."""

#: Ventana por defecto si la sesión no informó su tamaño, en píxeles CSS.
DEFAULT_VIEWPORT = (1280, 800)

#: Radio de cada punto en el mapa, en píxeles CSS. Más grande en la mirada, que es menos precisa.
RADIUS_PX: dict[str, float] = {"click": 14.0, "cursor": 10.0, "gaze": 40.0}

#: Altura máxima del fondo neutro, en píxeles CSS, para páginas muy largas.
MAX_BLANK_HEIGHT = 3000

#: Colores del mapa, de poca a mucha intensidad: azul, verde, amarillo y rojo.
_STOPS = np.array([[0, 70, 255], [0, 200, 120], [255, 220, 0], [230, 30, 30]], dtype=float)

_NUMERIC_SEGMENT = re.compile(r"(?<=/)[0-9]+(?=/|$)")


def screen_key(url: str) -> str:
    """Pantalla de una dirección, con la misma regla que el análisis.

    Quita el origen, la consulta y los fragmentos que no son rutas; cambia los
    identificadores numéricos por ``{id}``; y en una aplicación de una sola
    página con rutas en el fragmento (``#/carrito``), usa esa ruta.

    Args:
        url: Dirección capturada.

    Returns:
        Pantalla normalizada, por ejemplo ``/product/{id}``.
    """
    parsed = urlsplit(url)
    path = _NUMERIC_SEGMENT.sub("{id}", parsed.path or "/")
    fragment = parsed.fragment.removeprefix("!")
    if fragment.startswith("/"):
        route = _NUMERIC_SEGMENT.sub("{id}", urlsplit(fragment).path or "/")
        return route if path == "/" else f"{path}#{route}"
    return path


def with_scroll(events: pd.DataFrame) -> pd.DataFrame:
    """Agrega a cada evento el scroll de la página en ese momento y su pantalla.

    El scroll sale del último evento ``scroll`` de la misma visita a la pantalla:
    cada ``screen_change`` empieza de nuevo arriba.

    Args:
        events: Eventos de ``DashboardData.get_events``, en orden de tiempo.

    Returns:
        Copia con ``screen`` (normalizada), ``scroll_x`` y ``scroll_y``.
    """
    frame = events.copy()
    scroll_x, scroll_y = [], []
    current = (0.0, 0.0)
    for row in frame.itertuples():
        if row.type == "screen_change":
            current = (0.0, 0.0)
        elif row.type == "scroll" and isinstance(row.data, dict):
            current = (float(row.data.get("scroll_x", 0)), float(row.data.get("scroll_y", 0)))
        scroll_x.append(current[0])
        scroll_y.append(current[1])
    frame["screen"] = [screen_key(url) for url in frame["url"]]
    frame["scroll_x"] = scroll_x
    frame["scroll_y"] = scroll_y
    return frame


def points(events: pd.DataFrame, gaze: pd.DataFrame, layer: str) -> pd.DataFrame:
    """Posiciones de una capa en coordenadas de la página, con su pantalla.

    Args:
        events: Eventos de una sesión (``DashboardData.get_events``).
        gaze: Mirada válida de esa sesión (``DashboardData.get_gaze``).
        layer: ``click``, ``cursor`` o ``gaze``.

    Returns:
        ``t``, ``screen``, ``x`` e ``y``.

    Raises:
        ValueError: Si la capa no existe.
    """
    if layer not in LAYERS:
        raise ValueError(f"unknown heatmap layer: {layer}")
    columns = ["t", "screen", "x", "y"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    located = with_scroll(events)
    if layer in ("click", "cursor"):
        kind = "click" if layer == "click" else "mousemove"
        rows = located[(located["type"] == kind) & located["x"].notna()]
        return pd.DataFrame(
            {
                "t": rows["t"],
                "screen": rows["screen"],
                "x": rows["x"] + rows["scroll_x"],
                "y": rows["y"] + rows["scroll_y"],
            }
        ).reset_index(drop=True)
    valid = gaze[gaze["x"].notna()].sort_values("t") if not gaze.empty else gaze
    if valid.empty:
        return pd.DataFrame(columns=columns)
    # La mirada no trae su pantalla: es la del último cambio de pantalla anterior.
    changes = located[located["type"] == "screen_change"][["t", "screen"]].sort_values("t")
    changes["t"] = changes["t"].astype(float)
    joined = pd.merge_asof(
        valid[["t", "x", "y", "scroll_x", "scroll_y"]].astype(float), changes, on="t"
    )
    joined = joined[joined["screen"].notna()]
    return pd.DataFrame(
        {
            "t": joined["t"],
            "screen": joined["screen"],
            "x": joined["x"] + joined["scroll_x"],
            "y": joined["y"] + joined["scroll_y"],
        }
    ).reset_index(drop=True)


@dataclass(frozen=True)
class Heatmap:
    """Mapa de calor ya dibujado.

    Attributes:
        image: Imagen con el mapa sobre la captura o el fondo neutro.
        drawn: Puntos dibujados.
        outside: Puntos que caen fuera de la imagen (por ejemplo, más abajo de la captura).
    """

    image: Image.Image
    drawn: int
    outside: int


def render(
    xy: Sequence[tuple[float, float]] | np.ndarray,
    *,
    layer: str,
    background: Image.Image | None = None,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
) -> Heatmap:
    """Dibuja un mapa de calor.

    Args:
        xy: Posiciones en coordenadas de la página, en píxeles CSS.
        layer: Capa (define el radio de cada punto).
        background: Captura de la pantalla, o ``None`` para un fondo neutro.
        viewport: Tamaño de la ventana de la sesión en píxeles CSS: la captura
            se escala a ese ancho (en una pantalla con ``devicePixelRatio`` 2 tiene
            el doble de píxeles).

    Returns:
        El mapa y cuántos puntos se dibujaron y cuántos quedaron fuera.
    """
    positions = np.asarray(xy, dtype=float).reshape(-1, 2)
    width = int(viewport[0])
    if background is not None:
        height = max(1, round(background.height * width / background.width))
        base = background.convert("RGB").resize((width, height))
    else:
        lowest = float(positions[:, 1].max()) + 60 if len(positions) else 0
        height = int(min(MAX_BLANK_HEIGHT, max(viewport[1], lowest)))
        base = _blank(width, height)
    inside = (
        (positions[:, 0] >= 0)
        & (positions[:, 0] < width)
        & (positions[:, 1] >= 0)
        & (positions[:, 1] < height)
    )
    shown = positions[inside]
    if len(shown) == 0:
        return Heatmap(base, 0, int((~inside).sum()))
    density = _density(shown, width, height, RADIUS_PX[layer])
    overlay = _colorize(density)
    image = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    return Heatmap(image, int(inside.sum()), int((~inside).sum()))


def _blank(width: int, height: int) -> Image.Image:
    """Fondo neutro con una cuadrícula suave, para pantallas sin captura."""
    image = Image.new("RGB", (width, height), (246, 247, 249))
    draw = ImageDraw.Draw(image)
    for x in range(0, width, 100):
        draw.line([(x, 0), (x, height)], fill=(228, 231, 235))
    for y in range(0, height, 100):
        draw.line([(0, y), (width, y)], fill=(228, 231, 235))
    return image


def _density(positions: np.ndarray, width: int, height: int, radius: float) -> np.ndarray:
    """Densidad suavizada de los puntos, normalizada entre 0 y 1, del tamaño de la imagen.

    Se calcula en una cuadrícula 4 veces más chica y se suaviza con un filtro
    gaussiano separable, para que sea rápido con miles de puntos.
    """
    scale = 4
    grid_w, grid_h = max(1, width // scale), max(1, height // scale)
    counts, _, _ = np.histogram2d(
        positions[:, 1] / scale,
        positions[:, 0] / scale,
        bins=(grid_h, grid_w),
        range=((0, grid_h), (0, grid_w)),
    )
    sigma = max(1.0, radius / scale / 2)
    size = int(sigma * 3)
    kernel = np.exp(-0.5 * (np.arange(-size, size + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    smooth = np.apply_along_axis(np.convolve, 0, counts, kernel, mode="same")
    smooth = np.apply_along_axis(np.convolve, 1, smooth, kernel, mode="same")
    peak = smooth.max()
    if peak <= 0:
        return np.zeros((height, width))
    small = Image.fromarray((smooth / peak * 255).astype(np.uint8))
    return np.asarray(small.resize((width, height), Image.BILINEAR), dtype=float) / 255


def _colorize(density: np.ndarray) -> Image.Image:
    """Lleva la densidad a colores, transparente donde casi no hay nada."""
    positions = density * (len(_STOPS) - 1)
    low = np.clip(np.floor(positions).astype(int), 0, len(_STOPS) - 2)
    fraction = (positions - low)[..., None]
    rgb = _STOPS[low] * (1 - fraction) + _STOPS[low + 1] * fraction
    alpha = np.where(density < 0.03, 0, np.clip(density * 1.6, 0, 1) * 170)
    rgba = np.dstack([rgb, alpha]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")
