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
from collections import deque
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
