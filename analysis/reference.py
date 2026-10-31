"""Etapa 6 del análisis: comparación con las referencias.

Para cada tarea de una sesión guiada (``data.tasks``):

- alinear los pasos del participante con los de cada referencia confirmada
  (``data.references``) por pantalla, texto y rol del elemento;
- decidir el éxito: la tarea llegó a la condición final y cumplió los pasos
  obligatorios (``required_steps``);
- contar los pasos, el punto de desvío (primer paso que no coincide con el
  siguiente esperado de ninguna referencia) y el tiempo fuera de ruta.

Las sesiones que no son guiadas no tienen resultados por tarea.

``extract_drafts`` extrae las rutas de las grabaciones de referencia y propone
condiciones con la URL final y los textos y roles observados en esa pantalla.
El cierre ``ended_by = reference`` acredita una condición final detectada en
la página cuando su texto no está en los eventos. Se exige también haber
alcanzado el final de esa ruta y cumplido sus pasos obligatorios.
"""

import math
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters
from analysis.screens import _normalize_url
from shared import contracts


def extract_steps(events: pd.DataFrame) -> list[dict[str, Any]]:
    """Extrae pasos en orden temporal, con la pantalla original del contrato.

    Args:
        events: Eventos de una tarea, con URL y título separados por el repositorio.

    Returns:
        Clics interactivos, envíos con formulario identificado y cambios de pantalla.
    """
    kinds = contracts.enums()["step_type"]
    steps = []
    for event in events[events["type"].isin(kinds)].sort_values("t", kind="stable").itertuples():
        element = event.element
        if event.type != "screen_change":
            if not isinstance(element, dict):
                continue
            if event.type == "click" and not element.get("interactive", False):
                continue
        steps.append(
            {
                "t": event.t,
                "type": event.type,
                "screen": {"url": event.url, "title": event.title},
                "element": None if event.type == "screen_change" else element,
            }
        )
    return steps


def extract_drafts(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Prepara una referencia en borrador por tarea terminada de una grabación.

    Args:
        data: Datos limpios y con pantallas de la sesión.
        params: Parámetros del análisis.

    Returns:
        Tabla ``reference_draft``; vacía fuera del modo ``reference``. Omite tareas
        abandonadas, intervalos inválidos y tareas sin pasos observados.
    """
    if data.session.mode != "reference":
        return columns.empty("reference_draft")
    grouped = {task_id: events for task_id, events in data.events.groupby("task_id", sort=False)}
    rows = []
    for task in data.tasks.itertuples():
        if (
            task.ended_by == "gave_up"
            or not math.isfinite(task.t_start)
            or not math.isfinite(task.t_end)
            or task.t_end < task.t_start
            or task.task_id not in grouped
        ):
            continue
        events = grouped[task.task_id]
        events = events[
            events["t"].between(task.t_start, task.t_end) & events["type"].ne("camera_gap")
        ].sort_values("t", kind="stable")
        steps = extract_steps(events)
        if not steps:
            continue
        rows.append(
            {
                "task_id": task.task_id,
                "steps": steps,
                "candidates": _candidates(events),
                "duration_ms": task.t_end - task.t_start,
            }
        )
    return columns.frame("reference_draft", rows)


def _candidates(events: pd.DataFrame) -> list[dict[str, str]]:
    """Propone condiciones del último tramo de pantalla, sin inferir textos del DOM."""
    final = events.iloc[-1]
    candidates = [{"type": "url_pattern", "pattern": _normalize_url(final["url"])}]
    seen = set()
    for event in reversed(list(events.itertuples())):
        if (
            event.type == "screen_change"
            or event.url != final["url"]
            or event.title != final["title"]
        ):
            break
        element = event.element
        if isinstance(element, dict):
            text = element.get("text")
            if isinstance(text, str) and text.strip():
                conditions = [{"type": "visible_text", "text": text.strip()}]
                role = element.get("role")
                if isinstance(role, str) and role.strip():
                    conditions.append(
                        {"type": "element_present", "text": text.strip(), "role": role.strip()}
                    )
                for condition in conditions:
                    key = tuple(sorted(condition.items()))
                    if key not in seen:
                        candidates.append(condition)
                        seen.add(key)
    return candidates


def compare(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Compara cada tarea de la sesión con sus referencias.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        params: Parámetros del análisis.

    Returns:
        Una fila por tarea, con las columnas de ``task_result``; vacío si la
        sesión no es guiada. Sin una referencia utilizable, el éxito es falso y
        el desvío y el tiempo fuera de ruta son desconocidos (vacíos). Entre
        varias rutas, el desvío usa el mayor índice esperado en ese momento.

    Raises:
        ValueError: Si una tarea tiene un intervalo temporal inválido.
    """
    if data.session.mode != "guided":
        return columns.empty("task_result")
    references = {}
    for row in data.references.itertuples():
        document = {
            "steps": row.steps,
            "candidates": [],
            "end_condition": row.end_condition,
            "required_steps": row.required_steps,
        }
        if (
            not row.steps
            or row.end_condition is None
            or contracts.validate("reference", document)
            or any(index >= len(row.steps) for index in row.required_steps)
        ):
            continue
        references.setdefault(row.task_id, []).append(row)
    ambiguous = _ambiguous_urls(data, references)
    grouped = {task_id: events for task_id, events in data.events.groupby("task_id", sort=False)}
    rows = []
    for task in data.tasks.itertuples():
        if (
            not math.isfinite(task.t_start)
            or not math.isfinite(task.t_end)
            or task.t_end < task.t_start
        ):
            raise ValueError(f"task {task.task_id}: invalid time interval")
        events = grouped.get(task.task_id)
        if events is None:
            events = columns.empty("events")
        events = events[
            events["t"].between(task.t_start, task.t_end) & events["type"].ne("camera_gap")
        ].sort_values("t", kind="stable")
        steps = extract_steps(events)
        routes = [
            _Route(
                [_step_key(step, ambiguous) for step in row.steps],
                set(row.required_steps),
                row.end_condition,
            )
            for row in references.get(task.task_id, [])
        ]
        deviation = off_since = None
        off_path_ms = 0.0 if routes else None
        for step in steps:
            key = _step_key(step, ambiguous)
            expected = max((route.cursor for route in routes), default=0)
            # Cada ruta avanza de forma independiente; ninguna mezcla obligaciones
            # de referencias distintas. No usar un generador con any: cortaría avances.
            matches = [route.advance(key, _control_key(step, key)) for route in routes]
            if not routes:
                continue
            if any(matches):
                if off_since is not None:
                    off_path_ms += step["t"] - off_since
                    off_since = None
            else:
                if deviation is None:
                    deviation = expected
                if off_since is None:
                    off_since = step["t"]
        if off_since is not None:
            off_path_ms += task.t_end - off_since
        candidates = _candidates(events) if not events.empty else []
        final_context = (
            _screen_key(events.iloc[-1]["url"], events.iloc[-1]["title"], ambiguous)
            if not events.empty
            else None
        )
        success = any(
            route.required.issubset(route.matched)
            and _end_reached(route, candidates, task.ended_by, final_context)
            for route in routes
        )
        rows.append(
            {
                "task_id": task.task_id,
                "success": success,
                "duration_ms": task.t_end - task.t_start,
                "steps": len(steps),
                "deviation_step": deviation,
                "off_path_ms": off_path_ms,
            }
        )
    return columns.frame("task_result", rows)


def _text(value: str | None) -> str:
    """Normaliza espacios sin cambiar mayúsculas ni el contenido capturado."""
    return " ".join((value or "").split())


def _ambiguous_urls(data: SessionData, references: dict) -> set[str]:
    """Localiza URLs compartidas por pantallas con títulos distintos."""
    titles: dict[str, set[str]] = {}
    for row in data.events[data.events["type"] != "camera_gap"].itertuples():
        if _text(row.title):
            titles.setdefault(row.url, set()).add(_text(row.title))
    for rows in references.values():
        for row in rows:
            for step in row.steps:
                screen = step["screen"]
                if _text(screen["title"]):
                    titles.setdefault(screen["url"], set()).add(_text(screen["title"]))
    return {url for url, values in titles.items() if len(values) > 1}


def _screen_key(url: str, title: str, ambiguous: set[str]) -> tuple:
    """Comparte patrones de URL y distingue títulos solo cuando hay ambigüedad."""
    return (_normalize_url(url), _text(title) if url in ambiguous else "")


def _step_key(step: dict, ambiguous: set[str]) -> tuple:
    """Prioriza pantalla, texto y rol; sin texto, usa el id o selector capturado."""
    screen = step["screen"]
    element = step["element"] or {}
    text, role = _text(element.get("text")), _text(element.get("role"))
    identity = "" if text else _element_identity(element)
    return (
        step["type"],
        *_screen_key(screen["url"], screen["title"], ambiguous),
        text,
        role,
        identity,
    )


def _element_identity(element: dict) -> str:
    """Prefiere un id estable al selector estructural, sin consultar valores de campos."""
    return f"#{element['id']}" if element.get("id") else element.get("selector", "")


def _control_key(step: dict, key: tuple) -> tuple | None:
    """Identifica repeticiones de un mismo control persistente entre pantallas."""
    element = step["element"]
    if not element or not _element_identity(element):
        return None
    return (step["type"], key[3], key[4], _element_identity(element))


@dataclass
class _Route:
    """Progreso independiente de una referencia y sus pasos efectivamente observados."""

    keys: list[tuple]
    required: set[int]
    condition: dict
    cursor: int = 0
    matched: set[int] = field(default_factory=set)
    seen: set[tuple] = field(default_factory=set)
    controls: set[tuple] = field(default_factory=set)
    screens: set[tuple] = field(default_factory=set)
    positions: dict[tuple, list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Indexa posiciones para evitar recorrer prefijos en cada paso."""
        for index, key in enumerate(self.keys):
            self.positions.setdefault(key, []).append(index)

    def advance(self, key: tuple, control: tuple | None) -> bool:
        """Avanza al esperado, admite repeticiones y registra saltos como desvíos."""
        if self.cursor < len(self.keys) and key == self.keys[self.cursor]:
            index = self.cursor
            on_path = True
        elif (
            key in self.seen
            or control is not None
            and control in self.controls
            or (key[0] == "screen_change" and key[1:3] in self.screens)
        ):
            return True
        else:
            positions = self.positions.get(key, [])
            position = bisect_left(positions, self.cursor)
            if position == len(positions):
                return False
            index = positions[position]
            on_path = False
        self.matched.add(index)
        self.seen.add(key)
        self.screens.add(key[1:3])
        if control is not None:
            self.controls.add(control)
        self.cursor = index + 1
        return on_path


def _end_reached(
    route: _Route, candidates: list[dict], ended_by: str, final_context: tuple | None
) -> bool:
    """Exige evidencia final o el cierre automático junto al final de la misma ruta."""
    condition = route.condition
    kind = condition["type"]
    if kind == "url_pattern":
        return any(
            candidate["type"] == kind
            and candidate["pattern"] == _normalize_url(condition["pattern"])
            for candidate in candidates
        )
    for candidate in candidates:
        if candidate["type"] != kind:
            continue
        if _text(condition["text"]) in _text(candidate["text"]) and (
            kind == "visible_text" or _text(condition["role"]) == _text(candidate["role"])
        ):
            return True
    return (
        ended_by == "reference"
        and len(route.keys) - 1 in route.matched
        and final_context == route.keys[-1][1:3]
    )
