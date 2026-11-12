"""Lo que dice cada mapa de calor, en números: explicación y resúmenes por capa.

Un mapa de calor muestra dónde se concentra algo, pero no cuánto ni sobre qué.
Este módulo acompaña cada capa con:

- una **explicación** de qué representa y cómo leerla;
- el **reparto por zonas** de la pantalla (cuadrícula de 3 × 3 de la primera
  vista, más lo que quedó debajo, al que se llega con scroll);
- en **clics**, los elementos que más se clicaron y cuántos clics cayeron en
  elementos que no responden;
- en **cursor**, cuánto recorrió;
- en **mirada**, el tiempo estimado sobre cada elemento (con la atribución por
  probabilidad del análisis), cuánto quedó sin asignar y en qué estados estuvo
  la mirada que el mapa no dibuja (fuera de la pantalla, parpadeo…).

Funciones puras sobre DataFrames de ``dashboard.data``: no importa Streamlit.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd

from dashboard.heatmap import screen_key, with_scroll

EXPLANATIONS: Mapping[str, str] = {
    "click": (
        "**Qué muestra:** cada clic es un punto, en la posición de la página donde se hizo "
        "(con el scroll de ese momento). Los colores van de azul (pocos clics) a rojo (la zona "
        "con más clics de esta pantalla): son relativos a esta pantalla, no a otras. "
        "**Cómo leerlo:** manchas sobre lo que no es un enlace o un botón indican que la gente "
        "esperaba que eso respondiera; muchas manchas dispersas, que no encuentra dónde ir."
    ),
    "cursor": (
        "**Qué muestra:** las posiciones registradas del cursor mientras se movía (una muestra "
        "cada pocos milisegundos), con el mismo color relativo que los clics. "
        "**Cómo leerlo:** el cursor acompaña a la vista solo en parte; zonas calientes sin clics "
        "suelen ser lugares por donde se pasó buscando o donde se dudó antes de elegir."
    ),
    "gaze": (
        "**Qué muestra:** dónde se estima que miraba la persona, con la cámara web, una muestra "
        "por cuadro mientras miraba la pantalla. Usa la mirada reprocesada al cerrar la sesión "
        "si existe. El radio de cada punto es mayor porque la estimación tiene un error de unos "
        "2 a 4 grados (unos 100 a 150 píxeles): se lee **por zonas y elementos grandes**, no por "
        "botones pequeños. **Cómo leerlo:** lo que nunca se calienta probablemente no se vio; "
        "las gráficas de abajo dicen sobre qué elementos y cuánto tiempo, con su probabilidad."
    ),
}
"""Explicación de cada capa, en Markdown."""

ROWS = ("Arriba", "Medio", "Abajo", "Debajo (con scroll)")
"""Filas del reparto por zonas: tres de la primera vista y lo que quedó debajo."""

COLUMNS = ("Izquierda", "Centro", "Derecha")
"""Columnas del reparto por zonas."""

STATE_LABELS: Mapping[str, str] = {
    "on_screen": "Mira la pantalla",
    "low_confidence": "Mira la pantalla (confianza baja)",
    "off_screen": "Fuera de la pantalla",
    "blink": "Parpadeo",
    "no_face": "Sin rostro",
    "uncalibrated": "Sin calibrar",
}
"""Etiquetas en español de ``gaze_state``."""

UNASSIGNED_LABEL = "Sin asignar (vacío, distracción)"
"""Etiqueta de las fijaciones que no se atribuyen a ningún elemento."""


def zone_shares(xy: np.ndarray, viewport: tuple[int, int]) -> pd.DataFrame:
    """Reparto de los puntos de un mapa por zonas de la pantalla.

    Args:
        xy: Posiciones en coordenadas de la página (``x``, ``y``).
        viewport: Ancho y alto de la ventana, en píxeles CSS.

    Returns:
        Una fila por zona (``row``, ``column``, ``count``, ``share`` entre 0 y 1),
        con todas las zonas aunque estén vacías.
    """
    positions = np.asarray(xy, dtype=float).reshape(-1, 2)
    width, height = float(viewport[0]), float(viewport[1])
    column = np.clip((positions[:, 0] * 3 // width).astype(int), 0, 2)
    row = np.where(
        positions[:, 1] >= height, 3, np.clip((positions[:, 1] * 3 // height).astype(int), 0, 2)
    )
    counts = np.zeros((len(ROWS), len(COLUMNS)), int)
    np.add.at(counts, (row, column), 1)
    total = counts.sum()
    return pd.DataFrame(
        [
            {
                "row": ROWS[r],
                "column": COLUMNS[c],
                "count": int(counts[r, c]),
                "share": float(counts[r, c] / total) if total else 0.0,
            }
            for r in range(len(ROWS))
            for c in range(len(COLUMNS))
        ]
    )


def element_label(element: Mapping | None) -> str:
    """Nombre legible de un elemento: su texto visible o, si no tiene, etiqueta e id.

    Args:
        element: Descriptor del elemento de un evento (``element.schema.json``).

    Returns:
        Por ejemplo ``"Ir a pagar" (button)`` o ``input #email``.
    """
    if not isinstance(element, Mapping):
        return "(sin elemento)"
    tag = element.get("tag") or "?"
    text = (element.get("text") or "").strip()
    if text:
        short = text if len(text) <= 40 else f"{text[:39]}…"
        return f"“{short}” ({tag})"
    identifier = element.get("id")
    return f"{tag} #{identifier}" if identifier else f"{tag} {element.get('selector', '')}".strip()


def labels_by_selector(events: pd.DataFrame) -> dict[str, str]:
    """Nombre legible de cada selector que aparece en los eventos de una sesión.

    La disposición de la pantalla no guarda texto; los eventos sí guardan el de
    los elementos con que se interactuó. Se usa para nombrar los elementos de la mirada.

    Args:
        events: Eventos de una sesión (``DashboardData.get_events``).

    Returns:
        Selector → nombre.
    """
    labels: dict[str, str] = {}
    if events.empty:
        return labels
    for element in events["element"]:
        if isinstance(element, Mapping) and element.get("selector"):
            labels.setdefault(element["selector"], element_label(element))
    return labels


def top_clicked(events: pd.DataFrame, screen: str, limit: int = 10) -> pd.DataFrame:
    """Elementos más clicados en una pantalla.

    Args:
        events: Eventos de una o varias sesiones (con ``url`` y ``element``).
        screen: Pantalla normalizada (``heatmap.screen_key``).
        limit: Cuántos elementos devolver.

    Returns:
        ``label``, ``clicks`` e ``interactive`` (si el elemento responde a clics),
        de más a menos clics.
    """
    columns = ["label", "clicks", "interactive"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    clicks = events[(events["type"] == "click")]
    clicks = clicks[[screen_key(url) == screen for url in clicks["url"]]]
    if clicks.empty:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(
        {
            "label": [element_label(e) for e in clicks["element"]],
            "interactive": [
                bool(e.get("interactive")) if isinstance(e, Mapping) else False
                for e in clicks["element"]
            ],
        }
    )
    grouped = frame.groupby(["label", "interactive"]).size().rename("clicks").reset_index()
    return (
        grouped.sort_values("clicks", ascending=False).head(limit)[columns].reset_index(drop=True)
    )


def cursor_distance_px(events: pd.DataFrame, screen: str) -> float:
    """Recorrido total del cursor en una pantalla, en píxeles CSS.

    Args:
        events: Eventos de una sesión.
        screen: Pantalla normalizada.

    Returns:
        Suma de las distancias entre muestras seguidas de la misma visita.
    """
    if events.empty:
        return 0.0
    located = with_scroll(events)
    # Cada cambio de pantalla empieza una visita nueva: no se une con la anterior.
    located["visit"] = (located["type"] == "screen_change").cumsum()
    moves = located[
        (located["type"] == "mousemove") & located["x"].notna() & (located["screen"] == screen)
    ]
    total = 0.0
    for _, visit in moves.groupby("visit"):
        xy = visit[["x", "y"]].to_numpy(float)
        total += float(np.hypot(*np.diff(xy, axis=0).T).sum()) if len(xy) > 1 else 0.0
    return total


def gaze_dwell(
    fixations: pd.DataFrame,
    attribution: pd.DataFrame,
    screen: str,
    labels: Mapping[str, str] | None = None,
    limit: int = 10,
) -> pd.DataFrame:
    """Tiempo de mirada estimado sobre cada elemento de una pantalla.

    Cada fijación reparte su duración entre sus candidatos según la
    probabilidad de la mirada sola (``p_gaze``): una fijación de 400 ms con 75 %
    sobre el buscador suma 300 ms al buscador. Así el tiempo no exagera lo dudoso.

    Args:
        fixations: Filas de ``gaze_fixation`` (``fixation``, ``t_start``,
            ``t_end``, ``screen``); con varias sesiones, también ``session_id``.
        attribution: Filas de ``gaze_attribution`` de las mismas sesiones.
        screen: Pantalla normalizada.
        labels: Nombre legible de cada selector, si se conoce.
        limit: Cuántos elementos devolver, además de sin asignar.

    Returns:
        ``label``, ``seconds``, ``fixations`` (en cuántas fue el más probable),
        ``interactive`` y ``unassigned``; de más a menos tiempo, con la fila de
        sin asignar al final si la hay.
    """
    columns = ["label", "seconds", "fixations", "interactive", "unassigned"]
    if fixations.empty or attribution.empty:
        return pd.DataFrame(columns=columns)
    keys = ["session_id", "fixation"] if "session_id" in fixations else ["fixation"]
    here = fixations[[screen_key(url or "") == screen for url in fixations["screen"]]]
    if here.empty:
        return pd.DataFrame(columns=columns)
    here = here.assign(duration=(here["t_end"] - here["t_start"]).clip(lower=0) / 1000)
    joined = attribution.merge(here[[*keys, "duration", "element_selector"]], on=keys)
    joined["seconds"] = joined["p_gaze"] * joined["duration"]
    joined["best"] = joined["selector"] == joined["element_selector"]
    joined["key"] = joined["selector"].fillna("")
    grouped = joined.groupby("key").agg(
        seconds=("seconds", "sum"),
        fixations=("best", "sum"),
        interactive=("interactive", "first"),
        tag=("tag", "first"),
    )
    names = labels or {}
    rows = []
    for key, row in grouped.iterrows():
        unassigned = key == ""
        label = UNASSIGNED_LABEL if unassigned else names.get(key, _short_selector(key, row["tag"]))
        rows.append(
            {
                "label": label,
                "seconds": float(row["seconds"]),
                "fixations": int(row["fixations"]),
                "interactive": None if unassigned else bool(row["interactive"]),
                "unassigned": unassigned,
            }
        )
    frame = pd.DataFrame(rows, columns=columns)
    elements = frame[~frame["unassigned"]].sort_values("seconds", ascending=False).head(limit)
    result = pd.concat([elements, frame[frame["unassigned"]]], ignore_index=True)
    result["label"] = _unique(result["label"].tolist())
    return result


def gaze_state_shares(gaze: pd.DataFrame) -> pd.DataFrame:
    """Parte del tiempo en cada estado de la mirada.

    Args:
        gaze: Muestras de mirada con ``state`` (válidas e inválidas).

    Returns:
        ``state`` (etiqueta en español) y ``share`` entre 0 y 1, de mayor a menor.
    """
    if gaze.empty or "state" not in gaze:
        return pd.DataFrame(columns=["state", "share"])
    labels = gaze["state"].dropna().map(lambda state: STATE_LABELS.get(state, state))
    shares = labels.value_counts(normalize=True)
    return shares.rename("share").rename_axis("state").reset_index()


def _short_selector(selector: str, tag: object) -> str:
    """Nombre corto de un elemento sin texto conocido: el final de su selector.

    Con solo la etiqueta (``a``) no se distinguen dos enlaces; los dos últimos
    pasos del selector (``div.card › a:nth-of-type(2)``) sí, y se leen.
    """
    steps = [step.strip() for step in selector.split(">") if step.strip()]
    tail = " › ".join(steps[-2:]) if steps else str(tag)
    return tail if len(tail) <= 48 else f"…{tail[-47:]}"


def _unique(labels: list[str]) -> list[str]:
    """Agrega un número a los nombres repetidos, para que no se junten en una gráfica."""
    seen: dict[str, int] = {}
    result = []
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
        result.append(label if seen[label] == 1 else f"{label} ({seen[label]})")
    return result
