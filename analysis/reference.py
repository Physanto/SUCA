"""Etapa 5 del análisis: comparación con las referencias.

Qué hará, para cada tarea de una sesión guiada (``data.tasks``):

- alinear los pasos del participante con los de cada referencia confirmada
  (``data.references``) por pantalla, texto y rol del elemento;
- decidir el éxito: la tarea llegó a la condición final y cumplió los pasos
  obligatorios (``required_steps``);
- contar los pasos, el punto de desvío (primer paso que no coincide con el
  siguiente esperado de ninguna referencia) y el tiempo fuera de ruta.

Las sesiones que no son guiadas no tienen resultados por tarea.

``extract_drafts`` extrae las rutas de las grabaciones de referencia y propone
condiciones con la URL final y los textos y roles observados en esa pantalla.
La comparación de sesiones guiadas sigue pendiente.
"""

import math
import re
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters
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


def _normalize_url(url: str) -> str:
    """Obtiene el patrón de ruta de M5 sin depender de la etapa de pantallas de M4."""
    parsed = urlsplit(url)
    path = re.sub(r"(?<=/)[0-9]+(?=/|$)", "{id}", parsed.path or "/")
    fragment = parsed.fragment.removeprefix("!")
    if fragment.startswith("/"):
        route = re.sub(r"(?<=/)[0-9]+(?=/|$)", "{id}", urlsplit(fragment).path or "/")
        return route if path == "/" else f"{path}#{route}"
    return path


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
        sesión no es guiada.
    """
    return columns.empty("task_result")
