"""Zona y elemento de un punto de mirada, con la disposición registrada de la pantalla.

En vivo, la extensión pregunta a la página qué elemento hay bajo la mirada. Un
punto corregido después de la sesión ya no tiene página a la que preguntar: se
usa el registro ``layout`` vigente en ese momento (el último antes del punto),
que guarda los rectángulos de las regiones semánticas y de los elementos
interactivos visibles.

- **Zona:** la región semántica más pequeña que contiene el punto (la más
  interna, como la región más cercana que usa la extensión); si ninguna, la
  cuadrícula de 3 × 3 de la ventana, con los mismos nombres que ``gaze_zone``.
- **Elemento:** el elemento interactivo más pequeño que contiene el punto, o
  ``None``. La extensión, en vivo, guarda el elemento más interno bajo la
  mirada, sea o no interactivo; aquí solo se conocen los interactivos.

Los rectángulos se tomaron con el scroll de su registro: uno que no es fijo se
pasa a coordenadas de página sumando ese scroll, y el punto, sumando el suyo.

Funciones puras con numpy: se prueban sin la base.
"""

import numpy as np
import pandas as pd

_ROWS = ("top", "middle", "bottom")
_COLUMNS = ("left", "center", "right")


def grid_zone(x: np.ndarray, y: np.ndarray, width: np.ndarray, height: np.ndarray) -> list[str]:
    """Zona de la cuadrícula de 3 × 3 de la ventana, como la nombra la extensión.

    Args:
        x: Coordenadas horizontales en la ventana.
        y: Coordenadas verticales en la ventana.
        width: Ancho de la ventana de cada punto.
        height: Alto de la ventana de cada punto.

    Returns:
        Un valor de ``gaze_zone`` por punto (``grid_top_left`` …).
    """
    column = np.clip(np.floor(3 * np.asarray(x, float) / np.asarray(width, float)), 0, 2).astype(
        int
    )
    row = np.clip(np.floor(3 * np.asarray(y, float) / np.asarray(height, float)), 0, 2).astype(int)
    return [f"grid_{_ROWS[r]}_{_COLUMNS[c]}" for r, c in zip(row, column, strict=True)]


def _smallest_containing(
    page_x: np.ndarray,
    page_y: np.ndarray,
    view_x: np.ndarray,
    view_y: np.ndarray,
    items: list,
    scroll: tuple[float, float],
) -> np.ndarray:
    """Índice del rectángulo más pequeño que contiene cada punto, o -1."""
    if not items:
        return np.full(page_x.size, -1)
    boxes = np.array(
        [[i["box"]["x"], i["box"]["y"], i["box"]["w"], i["box"]["h"]] for i in items], float
    )
    fixed = np.array([bool(i["fixed"]) for i in items])
    # Los rectángulos no fijos pasan a coordenadas de página; los fijos se comparan en la ventana.
    left = boxes[:, 0] + np.where(fixed, 0, scroll[0])
    top = boxes[:, 1] + np.where(fixed, 0, scroll[1])
    px = np.where(fixed[None, :], view_x[:, None], page_x[:, None])
    py = np.where(fixed[None, :], view_y[:, None], page_y[:, None])
    inside = (px >= left) & (px < left + boxes[:, 2]) & (py >= top) & (py < top + boxes[:, 3])
    area = np.where(inside, boxes[:, 2] * boxes[:, 3], np.inf)
    best = area.argmin(axis=1)
    return np.where(np.isfinite(area.min(axis=1)), best, -1)


def assign(points: pd.DataFrame, layouts: pd.DataFrame) -> pd.DataFrame:
    """Zona y elemento de cada punto.

    Args:
        points: Puntos con ``t``, ``x``, ``y`` (en la ventana; ``NaN`` si no hay),
            ``scroll_x``, ``scroll_y``, ``viewport_width`` y ``viewport_height``.
        layouts: Filas de ``page_layout`` (``regions`` y ``elements`` ya son listas).

    Returns:
        DataFrame con el índice de ``points`` y las columnas ``zone`` y
        ``element_selector`` (``None`` donde no hay punto o no hay elemento).
    """
    result = pd.DataFrame(
        {"zone": None, "element_selector": None}, index=points.index, dtype=object
    )
    present = points["x"].notna() & points["y"].notna()
    if not present.any():
        return result
    selected = points[present]
    zones = pd.Series(
        grid_zone(
            selected["x"], selected["y"], selected["viewport_width"], selected["viewport_height"]
        ),
        index=selected.index,
        dtype=object,
    )
    elements = pd.Series(None, index=selected.index, dtype=object)
    if len(layouts):
        ordered = layouts.sort_values("t").reset_index(drop=True)
        times = ordered["t"].to_numpy(float)
        which = np.searchsorted(times, selected["t"].to_numpy(float), side="right") - 1
        for index in np.unique(which[which >= 0]):
            layout = ordered.iloc[int(index)]
            rows = selected[which == index]
            view_x = rows["x"].to_numpy(float)
            view_y = rows["y"].to_numpy(float)
            page_x = view_x + rows["scroll_x"].to_numpy(float)
            page_y = view_y + rows["scroll_y"].to_numpy(float)
            scroll = (float(layout["scroll_x"]), float(layout["scroll_y"]))
            regions = list(layout["regions"])
            found = _smallest_containing(page_x, page_y, view_x, view_y, regions, scroll)
            for label, k in zip(rows.index, found, strict=True):
                if k >= 0:
                    zones[label] = regions[k]["zone"]
            items = list(layout["elements"])
            found = _smallest_containing(page_x, page_y, view_x, view_y, items, scroll)
            for label, k in zip(rows.index, found, strict=True):
                if k >= 0:
                    elements[label] = items[k]["selector"]
    result.loc[selected.index, "zone"] = zones
    result.loc[selected.index, "element_selector"] = elements
    # Las celdas vacías quedan en None (no NaN): son textos opcionales.
    return result.astype(object).where(result.notna(), None)
