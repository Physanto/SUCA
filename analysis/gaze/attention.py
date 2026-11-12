"""Atribución de cada fijación a los elementos de la pantalla, con probabilidades.

La mirada por webcam tiene un error de varios grados: una fijación entre un
título y un buscador puede ser de cualquiera de los dos. En vez de asignarla al
elemento que contiene el punto, se calcula **la probabilidad de cada candidato**:

- **Candidatos:** los elementos de la disposición vigente (``page_layout``,
  interactivos y de contenido) a menos de ``candidate_radius_sigma`` desvíos del
  error, más el estado **sin asignar** (``selector`` nulo): la persona mira el
  vacío, está distraída o pensando. Mirar fuera de la pantalla ya lo marca el
  monitor de estado y no forma fijaciones.
- **Verosimilitud de un elemento:** la persona mira un punto cualquiera de su
  caja y la estimación se corre con un error gaussiano; es la integral del error
  sobre la caja dividida por su área. Un elemento grande reparte su
  verosimilitud en más superficie que uno pequeño. **Sin asignar** es uniforme
  en la ventana.
- **Previa:** ``unassigned_prior`` para sin asignar y el resto repartido por
  igual entre los elementos de la pantalla.
- **Secuencia:** un modelo oculto de Markov con avance y retroceso. Volver a
  fijar el mismo elemento (o seguir distraído) es ``stay_weight`` veces más
  probable que pasar a otro, y pasar a uno cercano es más probable que a uno
  lejano. Un hueco largo o un cambio de pantalla cortan la secuencia.

Hay **dos salidas**, que no se mezclan:

- ``p_gaze``: mirada y secuencia. Es la que se compara con la interacción en la
  pregunta P5: no sabe nada de los clics.
- ``p_attention``: **atención estimada**. Además, un clic o un foco sobre un
  elemento hace ``interaction_likelihood_ratio`` veces más verosímil que las
  fijaciones del tramo previo (``interaction_window_ms``) estuvieran sobre él.
  Sube la probabilidad, no la fija en 1: si la mirada estaba lejos del clic, el
  clic no la arrastra. Usarla en P5 la inflaría por construcción.

**El árbol de la pantalla** (``parent`` de cada elemento) resuelve lo ambiguo:
si dos enlaces pequeños vecinos se reparten la probabilidad, se sube al
ancestro que los reúne ("la tarjeta del producto, 85 %") y la fijación se marca
ambigua. Un ancestro siempre está entre los candidatos si lo está un
descendiente, porque su caja lo contiene.

**Mirada fija prolongada:** una fijación de ``long_stare_ms`` o más sin
interacción ni scroll se marca. Es un indicio de distracción o de pensar, no una
prueba: ningún sistema de mirada sabe si la persona atiende a lo que mira.

Funciones puras sobre DataFrames; el orquestador (``analysis/run.py``) carga y
guarda.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis import columns
from analysis.gaze import GazeSettings
from analysis.parameters import AttentionParams

INTERACTION_TYPES = ("click", "dblclick", "contextmenu", "focus_in")
"""Eventos sobre un elemento que suelen ir precedidos de mirarlo."""

ACTIVITY_TYPES = (
    *INTERACTION_TYPES,
    "scroll",
    "selection",
    "field_change",
    "form_submit",
)
"""Eventos que muestran actividad: con ellos una fijación larga no es mirada fija."""

_LOW_CONFIDENCE = "low_confidence"

_HALF_PI_SQRT = math.sqrt(math.pi / 2)
"""Error medio de una gaussiana circular en desvíos: E = σ·√(π/2)."""

_phi = np.vectorize(lambda z: 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))), otypes=[float])


@dataclass(frozen=True)
class GazeAttention:
    """Resultado de la atribución de una sesión.

    Attributes:
        fixations: Una fila por fijación con disposición (tabla ``gaze_fixation``).
        candidates: Una fila por fijación y candidato con probabilidad suficiente
            (tabla ``gaze_attribution``); ``selector`` nulo es sin asignar.
    """

    fixations: pd.DataFrame
    candidates: pd.DataFrame


@dataclass(frozen=True)
class _Screen:
    """Elementos de una disposición, en arreglos, en coordenadas de su ventana."""

    url: str | None
    width: float
    height: float
    scroll: tuple[float, float]
    selectors: list[str]
    tags: list[str]
    interactive: np.ndarray
    parents: np.ndarray
    boxes: np.ndarray
    fixed: np.ndarray

    def boxes_at(self, scroll_x: float, scroll_y: float) -> np.ndarray:
        """Cajas ``[x1, y1, x2, y2]`` en la ventana de un momento con otro scroll."""
        shift = np.where(self.fixed, 0.0, 1.0)[:, None] * np.array(
            [self.scroll[0] - scroll_x, self.scroll[1] - scroll_y]
        )
        left_top = self.boxes[:, :2] + shift
        return np.hstack([left_top, left_top + self.boxes[:, 2:]])


@dataclass
class _Step:
    """Una fijación con su pantalla, sus candidatos y su verosimilitud."""

    screen: _Screen
    candidates: np.ndarray
    likelihood: np.ndarray
    unassigned_likelihood: float
    centers: np.ndarray
    all_centers: np.ndarray


def error_sigma_px(
    error_deg: float | None, settings: GazeSettings, params: AttentionParams
) -> float:
    """Desvío del error de la mirada en uso natural, en píxeles CSS.

    El error medio medido en los puntos de control (o ``default_error_deg``) se
    agranda por ``natural_error_factor`` y se pasa a desvío de una gaussiana
    circular.

    Args:
        error_deg: Error medio de la mirada que usa el análisis, o ``None``.
        settings: Ajustes de la mirada (distancia y densidad de la pantalla).
        params: Parámetros de la atribución.

    Returns:
        Desvío en píxeles.
    """
    mean_deg = error_deg if error_deg is not None and error_deg > 0 else params.default_error_deg
    return mean_deg * params.natural_error_factor / _HALF_PI_SQRT * _deg_px(settings)


def fixations_of(samples: pd.DataFrame) -> pd.DataFrame:
    """Resume cada fijación de la mirada reprocesada.

    Args:
        samples: Filas de ``gaze_refined`` (``t``, ``x``, ``y``, ``scroll_x``,
            ``scroll_y``, ``state``, ``fixation``).

    Returns:
        Una fila por fijación, en orden de tiempo: ``fixation``, ``t_start``,
        ``t_end``, ``x``, ``y`` (centro en la ventana), ``scroll_x``,
        ``scroll_y`` y ``low_confidence`` (si la mayoría de sus cuadros la tiene).
    """
    rows = samples[samples["fixation"].notna() & samples["x"].notna() & samples["y"].notna()]
    if rows.empty:
        return pd.DataFrame(
            columns=["fixation", "t_start", "t_end", "x", "y", "scroll_x", "scroll_y"]
            + ["low_confidence"]
        )
    rows = rows.assign(low=rows["state"] == _LOW_CONFIDENCE)
    grouped = rows.groupby(rows["fixation"].astype(int))
    result = pd.DataFrame(
        {
            "t_start": grouped["t"].min(),
            "t_end": grouped["t"].max(),
            "x": grouped["x"].mean(),
            "y": grouped["y"].mean(),
            "scroll_x": grouped["scroll_x"].median(),
            "scroll_y": grouped["scroll_y"].median(),
            "low_confidence": grouped["low"].mean() > 0.5,
        }
    )
    return result.rename_axis("fixation").reset_index().sort_values("t_start", ignore_index=True)


def attribute(
    samples: pd.DataFrame,
    layouts: pd.DataFrame,
    interactions: pd.DataFrame,
    error_deg: float | None,
    settings: GazeSettings,
    params: AttentionParams,
) -> GazeAttention:
    """Atribuye cada fijación a los elementos de la pantalla.

    Args:
        samples: Mirada reprocesada (tabla ``gaze_refined``).
        layouts: Disposiciones de la sesión (``page_layout``; ``elements`` ya es lista).
        interactions: Eventos de interacción y actividad (``t``, ``type``,
            ``selector``), en orden de tiempo.
        error_deg: Error medio de la mirada usada, o ``None`` si no se midió.
        settings: Ajustes de la mirada.
        params: Parámetros de la atribución.

    Returns:
        Fijaciones y candidatos. Una fijación anterior a la primera disposición
        no tiene pantalla con la que atribuirse y queda fuera.
    """
    fixations = fixations_of(samples)
    if fixations.empty or layouts.empty:
        return GazeAttention(columns.empty("gaze_fixation"), columns.empty("gaze_attribution"))
    ordered = layouts.sort_values("t").reset_index(drop=True)
    times = ordered["t"].to_numpy(float)
    which = np.searchsorted(times, fixations["t_end"].to_numpy(float), "right")
    fixations = fixations.assign(layout=which - 1)
    fixations = fixations[fixations["layout"] >= 0].reset_index(drop=True)
    if fixations.empty:
        return GazeAttention(columns.empty("gaze_fixation"), columns.empty("gaze_attribution"))

    screens = {int(i): _screen(ordered.iloc[int(i)]) for i in fixations["layout"].unique()}
    sigma = error_sigma_px(error_deg, settings, params)
    near_px = params.near_distance_deg * _deg_px(settings)
    steps = [
        _step(
            screens[int(row.layout)],
            row,
            sigma * (params.low_confidence_factor if row.low_confidence else 1.0),
            params,
        )
        for row in fixations.itertuples()
    ]
    boosts = _interaction_boosts(fixations, steps, interactions, params)
    chains = _chains(fixations, steps, params)
    p_gaze = _posteriors(steps, chains, None, near_px, params)
    p_attention = _posteriors(steps, chains, boosts, near_px, params)
    stare = _long_stares(fixations, interactions, params)
    return GazeAttention(
        _fixation_rows(fixations, steps, p_gaze, p_attention, stare, sigma, params),
        _candidate_rows(fixations, steps, p_gaze, p_attention, params),
    )


def probability_seen(
    candidates: pd.DataFrame,
    fixations: pd.DataFrame,
    selector: str,
    t_start: float,
    t_end: float,
    *,
    attention: bool = False,
) -> float:
    """Probabilidad de que un elemento se haya mirado al menos una vez en un tramo.

    Responde preguntas como "¿vio el botón del paso siguiente antes del error?".
    Combina las fijaciones del tramo como si fueran independientes:
    ``1 − Π (1 − pᵢ)``. Es una aproximación: fijaciones vecinas están
    correlacionadas por la secuencia.

    Args:
        candidates: Filas de ``gaze_attribution``.
        fixations: Filas de ``gaze_fixation``.
        selector: Elemento buscado.
        t_start: Inicio del tramo.
        t_end: Fin del tramo.
        attention: Si usar la atención estimada (con interacción) en vez de la
            mirada sola. Para comparar con la interacción (P5), ``False``.

    Returns:
        Probabilidad entre 0 y 1; 0 si no hay fijaciones en el tramo.
    """
    inside = fixations[(fixations["t_end"] >= t_start) & (fixations["t_start"] <= t_end)]
    rows = candidates[
        candidates["fixation"].isin(inside["fixation"]) & (candidates["selector"] == selector)
    ]
    column = "p_attention" if attention else "p_gaze"
    return float(1.0 - np.prod(1.0 - rows[column].to_numpy(float)))


def _deg_px(settings: GazeSettings) -> float:
    """Píxeles CSS por grado a la distancia de referencia."""
    return settings.css_px_per_cm * settings.viewing_distance_cm * math.tan(math.radians(1))


def _element_prior(screen: _Screen, params: AttentionParams) -> float:
    """Probabilidad previa de cada elemento: lo que no es sin asignar, repartido por igual."""
    return (1.0 - params.unassigned_prior) / max(len(screen.selectors), 1)


def _screen(layout: pd.Series) -> _Screen:
    """Pasa una disposición a arreglos."""
    elements = list(layout["elements"])
    screen = layout["screen"]
    count = len(elements)
    boxes = np.array(
        [[e["box"]["x"], e["box"]["y"], e["box"]["w"], e["box"]["h"]] for e in elements], float
    ).reshape(count, 4)
    parents = np.array(
        [p if isinstance(p := e.get("parent"), int) and 0 <= p < count else -1 for e in elements],
        int,
    )
    return _Screen(
        url=screen.get("url") if isinstance(screen, dict) else None,
        width=float(layout["viewport_width"]),
        height=float(layout["viewport_height"]),
        scroll=(float(layout["scroll_x"]), float(layout["scroll_y"])),
        selectors=[e["selector"] for e in elements],
        tags=[e["tag"] for e in elements],
        # Los registros anteriores a la versión 1.6.0 solo tenían interactivos.
        interactive=np.array([bool(e.get("interactive", True)) for e in elements], bool),
        parents=parents,
        boxes=boxes,
        fixed=np.array([bool(e["fixed"]) for e in elements], bool),
    )


def _step(screen: _Screen, fixation: object, sigma: float, params: AttentionParams) -> _Step:
    """Candidatos de una fijación y su verosimilitud."""
    x, y = float(fixation.x), float(fixation.y)  # type: ignore[attr-defined]
    boxes = screen.boxes_at(float(fixation.scroll_x), float(fixation.scroll_y))  # type: ignore[attr-defined]
    dx = np.maximum.reduce([boxes[:, 0] - x, np.zeros(len(boxes)), x - boxes[:, 2]])
    dy = np.maximum.reduce([boxes[:, 1] - y, np.zeros(len(boxes)), y - boxes[:, 3]])
    near = np.hypot(dx, dy) <= params.candidate_radius_sigma * sigma
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    near &= area > 0
    candidates = np.flatnonzero(near)
    chosen = boxes[candidates]
    mass_x = _phi((chosen[:, 2] - x) / sigma) - _phi((chosen[:, 0] - x) / sigma)
    mass_y = _phi((chosen[:, 3] - y) / sigma) - _phi((chosen[:, 1] - y) / sigma)
    centers = np.column_stack([(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2])
    return _Step(
        screen=screen,
        candidates=candidates,
        likelihood=mass_x * mass_y / area[candidates],
        unassigned_likelihood=1.0 / (screen.width * screen.height),
        centers=centers[candidates],
        all_centers=centers,
    )


def _interaction_boosts(
    fixations: pd.DataFrame,
    steps: list[_Step],
    interactions: pd.DataFrame,
    params: AttentionParams,
) -> list[np.ndarray]:
    """Factor de la atención estimada para cada candidato de cada fijación."""
    boosts = [np.ones(len(step.candidates)) for step in steps]
    clicks = interactions[
        interactions["type"].isin(INTERACTION_TYPES) & interactions["selector"].notna()
    ]
    if clicks.empty:
        return boosts
    starts = fixations["t_start"].to_numpy(float)
    ends = fixations["t_end"].to_numpy(float)
    for t, selector in zip(clicks["t"].to_numpy(float), clicks["selector"], strict=True):
        # Las fijaciones que se solapan con el tramo previo a la interacción la preparan.
        before = np.flatnonzero((starts <= t) & (ends >= t - params.interaction_window_ms))
        for k in before:
            step = steps[k]
            match = np.array([step.screen.selectors[c] == selector for c in step.candidates], bool)
            # Un elemento se empuja una sola vez por fijación, aunque reciba clic y foco.
            boosts[k] = np.where(match, params.interaction_likelihood_ratio, boosts[k])
    return boosts


def _chains(fixations: pd.DataFrame, steps: list[_Step], params: AttentionParams) -> list[bool]:
    """Si cada fijación sigue la secuencia de la anterior (``False`` en la primera)."""
    linked = [False]
    for k in range(1, len(steps)):
        gap = fixations["t_start"].iat[k] - fixations["t_end"].iat[k - 1]
        same_screen = steps[k].screen.url == steps[k - 1].screen.url
        linked.append(bool(gap <= params.sequence_max_gap_ms and same_screen))
    return linked


def _transition(
    previous: _Step, current: _Step, near_px: float, params: AttentionParams
) -> np.ndarray:
    """Matriz de paso de los estados de una fijación a los de la siguiente.

    Filas: candidatos de ``previous`` y al final sin asignar; columnas: lo mismo
    de ``current``. Cada fila se normaliza sobre **todos** los elementos de la
    pantalla siguiente, no solo los candidatos: la probabilidad de ir a un
    elemento lejano también cuenta, aunque luego la mirada lo descarte.
    """
    count = len(current.screen.selectors)
    prior = _element_prior(current.screen, params)
    origins = list(previous.candidates)
    weights = np.zeros((len(origins) + 1, len(current.candidates) + 1))
    for row, origin in enumerate(origins):
        selector = previous.screen.selectors[origin]
        distance = np.hypot(*(current.all_centers - previous.centers[row]).T)
        follow = 1.0 + params.near_weight * np.exp(-distance / near_px)
        same = np.array([s == selector for s in current.screen.selectors], bool)
        follow = np.where(same, params.stay_weight, follow)
        total = prior * follow.sum() + params.unassigned_prior
        weights[row, :-1] = prior * follow[current.candidates] / total
        weights[row, -1] = params.unassigned_prior / total
    # Desde sin asignar: seguir distraído es más probable; los elementos, según la previa.
    total = prior * count + params.unassigned_prior * params.stay_weight
    weights[-1, :-1] = prior / total
    weights[-1, -1] = params.unassigned_prior * params.stay_weight / total
    return weights


def _posteriors(
    steps: list[_Step],
    linked: list[bool],
    boosts: list[np.ndarray] | None,
    near_px: float,
    params: AttentionParams,
) -> list[np.ndarray]:
    """Probabilidad de cada candidato (y de sin asignar, al final) en cada fijación."""
    emissions = []
    for k, step in enumerate(steps):
        likelihood = step.likelihood * (boosts[k] if boosts is not None else 1.0)
        emissions.append(np.append(likelihood, step.unassigned_likelihood))
    starts = [
        np.append(
            np.full(len(step.candidates), _element_prior(step.screen, params)),
            params.unassigned_prior,
        )
        for step in steps
    ]
    transitions = [
        _transition(steps[k - 1], steps[k], near_px, params) if linked[k] else None
        for k in range(len(steps))
    ]
    forward: list[np.ndarray] = []
    for k in range(len(steps)):
        carried = starts[k] if transitions[k] is None else forward[k - 1] @ transitions[k]
        alpha = carried * emissions[k]
        forward.append(alpha / alpha.sum() if alpha.sum() > 0 else starts[k])
    backward = [np.ones(len(e)) for e in emissions]
    for k in range(len(steps) - 2, -1, -1):
        matrix = transitions[k + 1]
        if matrix is None:
            continue
        beta = matrix @ (emissions[k + 1] * backward[k + 1])
        backward[k] = beta / beta.sum() if beta.sum() > 0 else np.ones(len(beta))
    result = []
    for alpha, beta in zip(forward, backward, strict=True):
        posterior = alpha * beta
        result.append(posterior / posterior.sum())
    return result


def _long_stares(
    fixations: pd.DataFrame, interactions: pd.DataFrame, params: AttentionParams
) -> np.ndarray:
    """Fijaciones largas sin interacción ni scroll."""
    activity = np.sort(
        interactions.loc[interactions["type"].isin(ACTIVITY_TYPES), "t"].to_numpy(float)
    )
    starts = fixations["t_start"].to_numpy(float)
    ends = fixations["t_end"].to_numpy(float)
    busy = np.searchsorted(activity, ends, "right") > np.searchsorted(activity, starts, "left")
    return (ends - starts >= params.long_stare_ms) & ~busy


def _resolve(
    step: _Step, posterior: np.ndarray, params: AttentionParams
) -> tuple[int | None, float | None, bool]:
    """Elemento que se da por mirado, subiendo por el árbol si hace falta.

    Returns:
        Posición del elemento en la pantalla (o ``None``), su probabilidad
        (sumada la de sus descendientes candidatos) y si fue necesario subir.
    """
    if not len(step.candidates):
        return None, None, False
    elements = posterior[:-1]
    position = {int(c): i for i, c in enumerate(step.candidates)}
    mass = elements.copy()
    for i, candidate in enumerate(step.candidates):
        ancestor = int(step.screen.parents[candidate])
        while ancestor >= 0:
            if ancestor in position:
                mass[position[ancestor]] += elements[i]
            ancestor = int(step.screen.parents[ancestor])
    best = int(np.argmax(elements))
    node = int(step.candidates[best])
    climbed = False
    while True:
        if mass[position[node]] >= params.confident_probability:
            return node, float(mass[position[node]]), climbed
        parent = int(step.screen.parents[node])
        if parent < 0 or parent not in position:
            return None, None, False
        node, climbed = parent, True


def _best(step: _Step, posterior: np.ndarray) -> tuple[str | None, float | None]:
    """Elemento más probable de una fijación y su probabilidad, o ``None`` sin candidatos."""
    if not len(step.candidates):
        return None, None
    i = int(np.argmax(posterior[:-1]))
    return step.screen.selectors[int(step.candidates[i])], float(posterior[i])


def _fixation_rows(
    fixations: pd.DataFrame,
    steps: list[_Step],
    p_gaze: list[np.ndarray],
    p_attention: list[np.ndarray],
    stare: np.ndarray,
    sigma: float,
    params: AttentionParams,
) -> pd.DataFrame:
    """Una fila de ``gaze_fixation`` por fijación."""
    rows = []
    for k, row in enumerate(fixations.itertuples()):
        step = steps[k]
        selectors = step.screen.selectors
        element, element_p = _best(step, p_gaze[k])
        attention, attention_p = _best(step, p_attention[k])
        resolved, resolved_p, climbed = _resolve(step, p_gaze[k], params)
        rows.append(
            {
                "fixation": int(row.fixation),
                "t_start": float(row.t_start),
                "t_end": float(row.t_end),
                "x": float(row.x),
                "y": float(row.y),
                "scroll_x": float(row.scroll_x),
                "scroll_y": float(row.scroll_y),
                "screen": step.screen.url,
                "sigma_px": sigma * (params.low_confidence_factor if row.low_confidence else 1.0),
                "element_selector": element,
                "element_p": element_p,
                "resolved_selector": selectors[resolved] if resolved is not None else None,
                "resolved_p": resolved_p,
                "ambiguous": climbed,
                "unassigned_p": float(p_gaze[k][-1]),
                "attention_selector": attention,
                "attention_p": attention_p,
                "long_stare": bool(stare[k]),
            }
        )
    return columns.frame("gaze_fixation", rows)


def _candidate_rows(
    fixations: pd.DataFrame,
    steps: list[_Step],
    p_gaze: list[np.ndarray],
    p_attention: list[np.ndarray],
    params: AttentionParams,
) -> pd.DataFrame:
    """Filas de ``gaze_attribution`` con probabilidad suficiente en alguna salida."""
    rows = []
    for k, number in enumerate(fixations["fixation"].astype(int)):
        step = steps[k]
        keep = np.maximum(p_gaze[k], p_attention[k]) >= params.min_probability
        for i in np.flatnonzero(keep):
            unassigned = i == len(step.candidates)
            element = None if unassigned else int(step.candidates[i])
            screen = step.screen
            rows.append(
                {
                    "fixation": int(number),
                    "selector": None if element is None else screen.selectors[element],
                    "tag": None if element is None else screen.tags[element],
                    "interactive": None if element is None else bool(screen.interactive[element]),
                    "p_gaze": float(p_gaze[k][i]),
                    "p_attention": float(p_attention[k][i]),
                }
            )
    return columns.frame("gaze_attribution", rows)
