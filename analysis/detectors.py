"""Etapa 4 del análisis: detectores de incidentes de fricción.

Cada detector es una estrategia registrada en ``DETECTORS``. ``detect`` los
ejecuta todos, valida lo que devuelve cada uno y une los incidentes. Agregar
un detector no cambia ``detect`` ni el orquestador.

Cómo agregar un detector
------------------------

1. Elige su tipo en la enumeración ``incident_type`` de ``contracts/enums.json``
   (si falta, pídelo: los tipos los define el contrato).
2. Escribe una clase con el atributo ``incident_type`` y el método ``find``, y
   regístrala con ``@DETECTORS.register``::

       @DETECTORS.register
       class DeadClickDetector:
           # Clic sin cambios en la página ni navegación en el tiempo de espera.
           incident_type = "dead_click"

           def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
               rows = []
               ...  # recorrer data.events con params.dead_click.wait_ms
               return columns.frame("incident", rows)

3. ``find`` devuelve un DataFrame con las columnas de la tabla ``incident``
   (``type``, ``t``, ``screen``, ``task_id``, ``element``), una fila por
   incidente, todas con ``type`` igual a su ``incident_type``. Sin incidentes,
   devuelve ``columns.empty("incident")``. ``columns.frame`` arma el DataFrame
   con los tipos correctos.
4. Lee los umbrales de ``params`` (``parameters.yaml``), nunca escritos en el código.
5. Prueba el detector con un caso que debe detectar y uno que no.

Un detector no modifica ``data``. Si falla o devuelve columnas incorrectas, la
etapa se detiene con un error que lo nombra.
"""

import math
from bisect import bisect_right
from collections import deque
from itertools import chain
from typing import Any, Protocol

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters
from analysis.registry import Registry
from shared import contracts


class Detector(Protocol):
    """Interfaz de un detector de incidentes.

    Attributes:
        incident_type: Tipo de incidente que produce (``incident_type``).
    """

    incident_type: str

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Busca los incidentes de su tipo en una sesión.

        Args:
            data: Datos de la sesión, limpios y con pantallas.
            params: Parámetros del análisis.

        Returns:
            DataFrame con las columnas de ``incident``; vacío si no hay ninguno.
        """
        ...


DETECTORS: Registry[Detector] = Registry(
    "detector", key="incident_type", allowed=contracts.enums()["incident_type"]
)
"""Detectores registrados."""


def detect(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Ejecuta todos los detectores registrados y une sus incidentes.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        params: Parámetros del análisis.

    Returns:
        Incidentes de todos los detectores, ordenados por tiempo, con las
        columnas de ``incident``. Vacío si no hay detectores o incidentes.

    Raises:
        RuntimeError: Si un detector falla; el mensaje lo nombra.
        columns.ColumnValidationError: Si un detector devuelve columnas,
            tipos o un ``type`` incorrectos.
    """
    found = []
    for detector in DETECTORS.all():
        label = f"detector {detector.incident_type}"
        try:
            result = detector.find(data, params)
        except Exception as error:
            raise RuntimeError(f"{label} failed: {error}") from error
        columns.validate(result, "incident", label=label)
        other_types = sorted(set(result["type"]) - {detector.incident_type})
        if other_types:
            raise columns.ColumnValidationError(
                label, "incident", [f"returned incidents of other types: {other_types}"]
            )
        found.append(result)
    return columns.concat("incident", found).sort_values("t", kind="stable", ignore_index=True)


def _context(event: Any) -> tuple[str, str, int | None]:
    """Identifica la página y tarea reales, además de la pantalla normalizada."""
    task = None if columns.is_missing(event.task_id) else int(event.task_id)
    return event.url, event.screen, task


def _element_identity(event: Any) -> tuple | None:
    """Identifica el elemento dentro de su contexto sin leer valores de campos."""
    if isinstance(event.element, dict):
        return (*_context(event), event.element["selector"])
    return None


def _text_field(element: Any) -> bool:
    """Reconoce controles donde el foco permite editar o seleccionar contenido."""
    return isinstance(element, dict) and (
        element.get("tag") in ("textarea", "select")
        or element.get("role") in ("textbox", "searchbox", "combobox", "spinbutton")
        or element.get("tag") == "input"
        and element.get("role") not in ("button", "radio", "checkbox", "switch", "slider")
    )


def _incident(event: Any, kind: str) -> dict[str, Any]:
    """Conserva tiempo, pantalla, tarea y elemento del evento que origina el incidente."""
    return {
        "type": kind,
        "t": event.t,
        "screen": event.screen,
        "task_id": event.task_id,
        "element": event.element,
    }


@DETECTORS.register
class RageClickDetector:
    """Una incidencia por ráfaga de clics próximos en espacio, tiempo y contexto."""

    incident_type = "rage_click"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Aplica una ventana móvil sin contar ventanas superpuestas como nuevas ráfagas."""
        settings = params.rage_click
        window: deque = deque()
        context = previous_time = None
        reported = False
        rows = []
        relevant = data.events[data.events["type"].isin(("click", "screen_change"))]
        for event in relevant.itertuples():
            if (
                event.type == "screen_change"
                or columns.is_missing(event.x)
                or columns.is_missing(event.y)
            ):
                window.clear()
                reported, context, previous_time = False, None, None
                continue
            current = _context(event)
            if current != context or (
                previous_time is not None and event.t - previous_time > settings.window_ms
            ):
                window.clear()
                reported = False
            context, previous_time = current, event.t
            while window and event.t - window[0].t > settings.window_ms:
                window.popleft()
            window.append(event)
            while window and any(
                math.hypot(click.x - window[0].x, click.y - window[0].y) > settings.radius_px
                for click in window
            ):
                window.popleft()
                reported = False
            if len(window) >= settings.min_clicks and not reported:
                rows.append(_incident(window[0], self.incident_type))
                reported = True
        return columns.frame("incident", rows)


@DETECTORS.register
class DeadClickDetector:
    """Clics sin cambios, navegación ni respuesta de foco dentro del plazo observado."""

    incident_type = "dead_click"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Correlaciona respuestas por clic y foco por elemento; exige la espera completa."""
        wait = params.dead_click.wait_ms
        clicks = []
        by_time: dict[float, list[int]] = {}
        pending: dict[tuple, list[int]] = {}
        answered: set[int] = set()
        focused = None
        for event in data.events.itertuples():
            if event.type == "click":
                index = len(clicks)
                clicks.append(event)
                by_time.setdefault(event.t, []).append(index)
                identity = _element_identity(event)
                if identity is not None:
                    if identity == focused:
                        answered.add(index)
                    else:
                        pending.setdefault(identity, []).append(index)
            elif event.type == "click_response" and isinstance(event.data, dict):
                if event.data.get("navigated") or event.data.get("mutation_count", 0) > 0:
                    for index in by_time.get(event.data["click_t"], ()):
                        if 0 <= event.t - clicks[index].t <= wait:
                            answered.add(index)
            elif event.type in ("focus_in", "field_change"):
                identity = _element_identity(event)
                if event.type == "focus_in":
                    focused = identity if _text_field(event.element) else None
                    if focused is None:
                        continue
                if identity is not None:
                    for index in pending.pop(identity, ()):
                        if 0 <= event.t - clicks[index].t <= wait:
                            answered.add(index)
            elif event.type == "focus_out":
                if _element_identity(event) == focused:
                    focused = None
            elif event.type == "screen_change":
                if clicks and 0 <= event.t - clicks[-1].t <= wait:
                    answered.add(len(clicks) - 1)
                focused = None
                pending.clear()
        observed = data.events.loc[data.events["type"] != "camera_gap", "t"]
        end = data.session.ended_at
        if end is None:
            end = float(observed.max()) if not observed.empty else data.session.started_at
        return columns.frame(
            "incident",
            [
                _incident(click, self.incident_type)
                for index, click in enumerate(clicks)
                if index not in answered and click.t + wait <= end
            ],
        )


@DETECTORS.register
class NavigationLoopDetector:
    """Regreso a una pantalla dentro de la ventana de visitas de la misma tarea."""

    incident_type = "navigation_loop"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Colapsa visitas consecutivas y fecha el regreso, cuando se confirma el bucle."""
        if params.navigation_loop_window < 3:
            return columns.empty("incident")
        visits: deque[str] = deque(maxlen=params.navigation_loop_window - 1)
        task = None
        rows = []
        for event in data.events[data.events["type"] != "camera_gap"].itertuples():
            current_task = _context(event)[2]
            if current_task != task:
                visits.clear()
                task = current_task
            if visits and visits[-1] == event.screen:
                continue
            if event.screen in visits:
                rows.append({**_incident(event, self.incident_type), "element": None})
            visits.append(event.screen)
        return columns.frame("incident", rows)


@DETECTORS.register
class LongPauseDetector:
    """Inactividad entre eventos observados de la misma tarea."""

    incident_type = "long_pause"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Ignora fallos de cámara y no inventa pausas antes o después de la captura."""
        previous = None
        rows = []
        for event in data.events[data.events["type"] != "camera_gap"].itertuples():
            if (
                previous is not None
                and _context(previous)[2] == _context(event)[2]
                and event.t - previous.t > params.long_pause_ms
            ):
                rows.append({**_incident(previous, self.incident_type), "element": None})
            previous = event
        return columns.frame("incident", rows)


def _element_area(element: Any, offset: tuple[float, float]) -> tuple | None:
    """Rectángulo interactivo en coordenadas de página; no conserva valores de campos."""
    if not isinstance(element, dict) or not element.get("interactive"):
        return None
    box = element["box"]
    if box["w"] <= 0 or box["h"] <= 0:
        return None
    return box["x"] + offset[0], box["y"] + offset[1], box["w"], box["h"]


def _inside(point: tuple[float, float], area: tuple) -> bool:
    """La esquina inferior derecha pertenece al exterior del rectángulo."""
    x, y, width, height = area
    return x <= point[0] < x + width and y <= point[1] < y + height


def _hover_catalog(data: SessionData) -> dict[tuple, dict[str, list[tuple]]]:
    """Geometría conocida por página: las capturas prevalecen sobre las referencias."""
    catalog: dict[tuple, dict[str, list[tuple]]] = {}
    labels = {
        (event.url, event.title): event.screen
        for event in data.events.itertuples()
        if event.type != "camera_gap"
    }
    for reference in data.references.itertuples():
        for step in reference.steps:
            page = step["screen"]
            screen = labels.get((page["url"], page["title"]))
            area = _element_area(step.get("element"), (0, 0))
            if screen is not None and area is not None:
                element = step["element"]
                catalog.setdefault((page["url"], screen), {})[element["selector"]] = [
                    (-math.inf, element, area)
                ]
    context = None
    offset = (0, 0)
    for event in data.events[data.events["type"] != "camera_gap"].itertuples():
        current = _context(event)[:2]
        if current != context or event.type == "screen_change":
            offset = (0, 0)
        context = current
        if event.type == "scroll":
            offset = event.data["scroll_x"], event.data["scroll_y"]
        area = _element_area(event.element, offset)
        if isinstance(event.element, dict):
            snapshots = catalog.setdefault(current, {}).setdefault(event.element["selector"], [])
            if not snapshots or snapshots[-1][1:] != (event.element, area):
                snapshots.append((event.t, event.element, area))
    return catalog


@DETECTORS.register
class HesitationDetector:
    """Cursor inmóvil sobre un elemento interactivo conocido y todavía sin activar."""

    incident_type = "hesitation"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Infiere el objetivo con sus rectángulos; la captura no incluye eventos hover."""
        catalog = _hover_catalog(data)
        events = data.events[data.events["type"] != "camera_gap"]
        end = data.session.ended_at
        if end is None:
            end = float(events["t"].max()) if not events.empty else data.session.started_at
        context = anchor = activated = None
        offset = (0, 0)
        checked = False
        rows = []
        for event in chain(events.itertuples(), (None,)):
            if event is not None:
                current = _context(event)
                if current != context or event.type == "screen_change":
                    anchor = activated = None
                    if (
                        context is None
                        or current[:2] != context[:2]
                        or event.type == "screen_change"
                    ):
                        offset = (0, 0)
                context = current
            until = end if event is None else event.t
            if anchor is not None and not checked and until - anchor.t > params.hesitation_ms:
                checked = True
                point = anchor.x + offset[0], anchor.y + offset[1]
                matches = []
                for snapshots in catalog.get(context[:2], {}).values():
                    position = bisect_right([snapshot[0] for snapshot in snapshots], anchor.t) - 1
                    _, element, area = snapshots[max(position, 0)]
                    if area is not None and _inside(point, area):
                        matches.append((element, area))
                if matches:
                    element, area = min(matches, key=lambda item: item[1][2] * item[1][3])
                    if activated is None or element["selector"] != activated[0]:
                        viewport_element = {
                            **element,
                            "box": {
                                "x": area[0] - offset[0],
                                "y": area[1] - offset[1],
                                "w": area[2],
                                "h": area[3],
                            },
                        }
                        rows.append(
                            {**_incident(anchor, self.incident_type), "element": viewport_element}
                        )
            if event is None:
                break
            if event.type == "scroll":
                offset = event.data["scroll_x"], event.data["scroll_y"]
                anchor = activated = None
            elif event.type == "mousemove":
                if columns.is_missing(event.x) or columns.is_missing(event.y):
                    anchor = activated = None
                    continue
                point = event.x + offset[0], event.y + offset[1]
                if activated is not None and not _inside(point, activated[1]):
                    activated = None
                if anchor is None or (event.x, event.y) != (anchor.x, anchor.y):
                    anchor, checked = event, False
            elif event.type in ("click", "dblclick", "contextmenu", "focus_in", "field_change"):
                area = _element_area(event.element, offset)
                if area is not None:
                    activated = event.element["selector"], area
                anchor = None
            elif event.type != "click_response":
                anchor = None
        return columns.frame("incident", rows)


@DETECTORS.register
class TaskOvertimeDetector:
    """Tareas guiadas cuya duración supera el factor de su referencia más larga."""

    incident_type = "task_overtime"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Solo compara tareas terminadas con referencias de duración positiva conocida."""
        if data.session.mode != "guided":
            return columns.empty("incident")
        durations: dict[int, float] = {}
        for reference in data.references.itertuples():
            duration = reference.duration_ms
            if not columns.is_missing(duration) and math.isfinite(duration) and duration > 0:
                durations[reference.task_id] = max(durations.get(reference.task_id, 0), duration)
        events = data.events[data.events["type"] != "camera_gap"]
        times = events["t"].tolist()
        screen_names = events["screen"].tolist()
        rows = []
        for task in data.tasks.itertuples():
            duration = durations.get(task.task_id)
            if duration is None:
                continue
            deadline = task.t_start + duration * params.task_overtime_factor
            if task.t_end > deadline:
                position = bisect_right(times, deadline) - 1
                rows.append(
                    {
                        "type": self.incident_type,
                        "t": deadline,
                        "task_id": task.task_id,
                        "screen": screen_names[position] if position >= 0 else None,
                        "element": None,
                    }
                )
        return columns.frame("incident", rows)
