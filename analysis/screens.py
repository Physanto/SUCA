"""Etapa 2 del análisis: identificación de las pantallas.

Normaliza la columna ``screen`` de ``data.events``, que al cargar es
la URL de cada evento:

- quitar identificadores numéricos y parámetros variables (``/order/8812`` →
  ``/order/{id}``);
- en aplicaciones de una sola página, tratar cada ruta como una pantalla;
- si dos pantallas comparten URL, distinguirlas por el título (``title``).

``url`` y ``title`` se conservan tal como se capturaron. Las etapas siguientes
agrupan por ``screen``.

"""

import re
from dataclasses import replace
from urllib.parse import urlsplit

from analysis.loader import SessionData
from analysis.parameters import Parameters

_NUMERIC_SEGMENT = re.compile(r"(?<=/)[0-9]+(?=/|$)")


def assign_screens(data: SessionData, params: Parameters) -> SessionData:
    """Asigna a cada evento su pantalla normalizada.

    Args:
        data: Datos de la sesión, ya limpios.
        params: Parámetros del análisis.

    Returns:
        Datos con ``events.screen`` normalizado. Si cambia algo, una copia
        (``dataclasses.replace``); nunca modifica ``data``.
    """
    events = data.events.copy()
    events["screen"] = events["url"].map(_normalize_url)
    titles = events["title"].str.strip()
    title_counts = (
        titles.where(titles.ne("")).groupby(events["url"], sort=False).transform("nunique")
    )
    use_title = title_counts.gt(1) & titles.ne("")
    events.loc[use_title, "screen"] = (
        events.loc[use_title, "screen"].astype(str) + " | " + titles.loc[use_title].astype(str)
    )
    return replace(data, events=events)


def _normalize_url(url: str) -> str:
    """Normaliza la ruta y conserva fragmentos que representan rutas de una SPA."""
    parsed = urlsplit(url)
    path = _NUMERIC_SEGMENT.sub("{id}", parsed.path or "/")
    fragment = parsed.fragment.removeprefix("!")
    if fragment.startswith("/"):
        route = _NUMERIC_SEGMENT.sub("{id}", urlsplit(fragment).path or "/")
        return route if path == "/" else f"{path}#{route}"
    return path
