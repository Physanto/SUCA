"""Interacciones compartidas por episodios y detectores de formularios."""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Any

from analysis import columns
from analysis.loader import SessionData


@dataclass
class Visit:
    """Una visita continua a una pantalla, con sus eventos observados."""

    screen: str
    start: float
    end: float
    events: list[Any]
    exited: bool = False
    exit_click: float | None = None


@dataclass
class FormRun:
    """Interacciones de un formulario dentro de una visita."""

    visit: Visit
    events: list[Any] = field(default_factory=list)

    @property
    def kind(self) -> str:
        """Clasifica por roles y por las pistas disponibles en los selectores."""
        elements = [event.element for event in self.events if isinstance(event.element, dict)]
        if any(_is_search(element) for element in elements):
            return "search"
        if any(_is_login(element) for element in elements):
            return "login"
        return "form"

    @property
    def start(self) -> float:
        """Inicio de la primera interacción con campos o del envío sin campos."""
        return next(
            event.t
            for event in self.events
            if event.type == "form_submit" or event.type != "focus_out" and is_field(event.element)
        )


def _context(event: Any) -> tuple:
    """Separa documentos y tareas sin comparar directamente los valores pd.NA."""
    task = None if columns.is_missing(event.task_id) else int(event.task_id)
    return event.url, event.screen, task


def visits(data: SessionData, *, split_context: bool = False) -> list[Visit]:
    """Separa visitas por cambios de pantalla y excluye los huecos de cámara."""
    visits: list[Visit] = []
    navigated_clicks = set()
    previous = None
    for event in data.events[data.events["type"] != "camera_gap"].itertuples():
        if (
            event.type == "click_response"
            and isinstance(event.data, dict)
            and event.data.get("navigated")
        ):
            navigated_clicks.add(event.data["click_t"])
        changed = previous is not None and (
            previous.url != event.url
            or previous.screen != event.screen
            or event.type == "screen_change"
        )
        if (
            not visits
            or event.screen != visits[-1].screen
            or split_context
            and (changed or _context(event) != _context(previous))
        ):
            if visits:
                visits[-1].end = event.t
                visits[-1].exited = changed
            visits.append(Visit(event.screen, event.t, event.t, []))
        visits[-1].events.append(event)
        visits[-1].end = event.t
        previous = event
    if visits and data.session.ended_at is not None:
        visits[-1].end = max(visits[-1].end, data.session.ended_at)
    for visit in visits:
        if visit.exited:
            visit.exit_click = next(
                (
                    event.t
                    for event in reversed(visit.events)
                    if event.type == "click" and event.t in navigated_clicks
                ),
                None,
            )
    return visits


def is_field(element: Any) -> bool:
    """Reconoce campos editables, sin incluir botones, radios ni casillas."""
    return isinstance(element, dict) and (
        element.get("tag") in ("textarea", "select")
        or element.get("role") in ("textbox", "searchbox", "combobox", "spinbutton")
        or element.get("tag") == "input"
        and element.get("role") not in ("button", "radio", "checkbox", "switch", "slider")
    )


def _is_search(element: dict[str, Any]) -> bool:
    """Busca evidencia de un campo o formulario de búsqueda."""
    return element.get("role") in ("search", "searchbox") or bool(
        re.search(r"\[type\s*=\s*['\"]?search\b", element.get("selector", ""), re.I)
    )


def _is_login(element: dict[str, Any]) -> bool:
    """Usa pistas de autenticación sin suponer atributos que no se capturan."""
    identity = f"{element.get('id') or ''} {element.get('selector', '')}"
    return bool(
        re.search(r"password|passwd|\bpwd\b|contrase[nñ]a|login|sign[-_]?in", identity, re.I)
    )


def _owner(element: dict[str, Any], forms: dict[str, dict]) -> str | None:
    """Asocia un campo por selector descendiente o por el rectángulo del formulario."""
    selector = element.get("selector", "")
    matches = []
    for key, form in forms.items():
        if selector == key or selector.startswith((key + " ", key + ">")):
            return key
        box, bounds = element.get("box", {}), form.get("box", {})
        if not box or not bounds or not bounds["w"] or not bounds["h"]:
            continue
        x, y = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        if bounds["x"] <= x <= bounds["x"] + bounds["w"] and (
            bounds["y"] <= y <= bounds["y"] + bounds["h"]
        ):
            matches.append((bounds["w"] * bounds["h"], key))
    return min(matches)[1] if matches else None


def form_runs(data: SessionData) -> list[FormRun]:
    """Agrupa interacciones observables sin mezclar visitas ni formularios conocidos."""
    runs = []
    for visit in visits(data, split_context=True):
        forms = {
            event.element["selector"]: event.element
            for event in visit.events
            if event.type == "form_submit" and isinstance(event.element, dict)
        }
        groups: dict[str, FormRun] = {}
        for event in visit.events:
            element = event.element
            if not isinstance(element, dict) or event.type not in (
                "click",
                "focus_in",
                "focus_out",
                "field_change",
                "validation_error",
                "form_submit",
            ):
                continue
            owner = _owner(element, forms)
            if event.type != "form_submit" and not is_field(element):
                if event.type != "click" or owner is None:
                    continue
            key = owner or ("__search__" if _is_search(element) else "__fields__")
            previous = groups.get(key)
            if (
                previous is not None
                and is_field(element)
                and event.type in ("click", "focus_in", "field_change")
            ):
                last_signal = next(
                    (
                        item
                        for item in reversed(previous.events)
                        if item.type in ("form_submit", "validation_error")
                    ),
                    None,
                )
                if last_signal is not None and last_signal.type == "form_submit":
                    runs.append(groups.pop(key))
            groups.setdefault(key, FormRun(visit)).events.append(event)
        runs.extend(
            run
            for run in groups.values()
            if any(
                event.type == "form_submit" or event.type != "focus_out" and is_field(event.element)
                for event in run.events
            )
        )
    return sorted(runs, key=lambda run: run.start)


def form_metrics(run: FormRun) -> tuple[int, int, int]:
    """Cuenta envíos lógicos, errores y reingresos con cambios tras recuperar foco."""
    return (
        len(form_submissions(run)),
        sum(event.type == "validation_error" for event in run.events),
        len(field_reentries(run)),
    )


def form_submissions(run: FormRun) -> list[Any]:
    """Agrupa envíos duplicados hasta editar campos o recibir un error de validación."""
    submissions = []
    pending = False
    for event in run.events:
        if (
            event.type == "validation_error"
            or event.type == "field_change"
            and is_field(event.element)
        ):
            pending = False
        elif event.type == "form_submit":
            if not pending:
                submissions.append(event)
            pending = True
    return submissions


def field_reentries(run: FormRun) -> list[Any]:
    """Exige un cambio tras volver a un campo ya editado, y conserva el inicio del retorno."""
    filled: set[str] = set()
    focused = anchor = None
    reentries = []
    for event in run.events:
        if event.type == "form_submit":
            focused = anchor = None
        if not is_field(event.element):
            continue
        key = event.element["selector"]
        if event.type == "focus_out":
            focused = anchor = None
        elif event.type in ("click", "focus_in", "field_change"):
            if focused != key:
                focused, anchor = key, event if key in filled else None
            if event.type == "field_change":
                if anchor is not None:
                    reentries.append(anchor)
                anchor = None
                filled.add(key)
    return reentries


def form_exit_time(run: FormRun) -> float:
    """Usa un clic con navegación confirmada o el fin observado de la visita."""
    click = run.visit.exit_click
    return click if click is not None and click >= run.start else run.visit.end


def result_link(element: Any) -> bool:
    """Reconoce enlaces candidatos a resultado, excluyendo navegación identificable."""
    if not isinstance(element, dict) or not (
        element.get("tag") == "a" or element.get("role") == "link"
    ):
        return False
    identity = f"{element.get('id') or ''} {element.get('selector', '')}"
    return element.get("role") != "menuitem" and not re.search(
        r"(?<![a-z0-9])(nav|menu|header|footer|back|home)(?![a-z0-9])", identity, re.I
    )


@dataclass
class SearchActivity:
    """Reformulaciones de una búsqueda hasta abrir un resultado o cambiar de actividad."""

    runs: list[FormRun]
    end: float
    result_click: Any = None


def search_activities(data: SessionData) -> list[SearchActivity]:
    """Comparte los límites de búsqueda entre episodios e incidentes."""
    events = list(data.events[data.events["type"] != "camera_gap"].itertuples())
    times = [event.t for event in events]
    responses = {
        event.data["click_t"]: event
        for event in events
        if event.type == "click_response" and isinstance(event.data, dict)
    }
    runs = form_runs(data)
    activities = []
    active = None
    result_context = None
    for index, run in enumerate(runs):
        if run.kind != "search":
            if active is not None:
                activities.append(active)
                active = None
            continue
        submits = [event for event in run.events if event.type == "form_submit"]
        if not submits:
            continue
        if active is not None and _context(run.events[0]) != result_context:
            activities.append(active)
            active = None
        if active is None:
            active = SearchActivity([], submits[-1].t)
        active.runs.append(run)
        clicks = [
            event.t
            for event in run.events
            if event.type == "click" and not is_field(event.element) and event.t <= submits[-1].t
        ]
        response = responses.get(clicks[-1]) if clicks else None
        active.end = response.t if response is not None else submits[-1].t
        result_context = _context(response if response is not None else submits[-1])
        stop = runs[index + 1].start if index + 1 < len(runs) else float("inf")
        start_index, stop_index = bisect_right(times, active.end), bisect_left(times, stop)
        if response is None:
            # Enter puede navegar sin un clic al que asociar click_response.
            for event in events[start_index:stop_index]:
                if _context(event)[2] != result_context[2]:
                    break
                if event.type == "screen_change":
                    active.end, result_context = event.t, _context(event)
                    start_index = bisect_right(times, active.end)
                    break
                if event.type in ("click", "focus_in", "field_change", "form_submit"):
                    break
        for event in events[start_index:stop_index]:
            if (
                event.type == "click"
                and _context(event) == result_context
                and result_link(event.element)
            ):
                active.end, active.result_click = event.t, event
                activities.append(active)
                active = None
                break
            if _context(event) != result_context:
                activities.append(active)
                active = None
                break
    if active is not None:
        activities.append(active)
    return activities
