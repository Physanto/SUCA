"""Etapa 3 del análisis: segmentación de la sesión en episodios.

Cada tipo de episodio (inicio de sesión, formulario, búsqueda, pantalla) lo
reconoce un detector de episodios registrado en ``EPISODE_DETECTORS``.
``detect`` los ejecuta todos, valida lo que devuelve cada uno y une los
episodios. Agregar un detector de episodios no cambia ``detect`` ni el
orquestador.

Cómo agregar un detector de episodios
-------------------------------------

1. Elige su tipo en la enumeración ``episode_type`` de ``contracts/enums.json``.
2. Escribe una clase con el atributo ``episode_type`` y el método ``find``, y
   regístrala con ``@EPISODE_DETECTORS.register``::

       @EPISODE_DETECTORS.register
       class ScreenEpisodes:
           # Un episodio por cada visita a una pantalla.
           episode_type = "screen"

           def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
               rows = []
               ...  # recorrer data.events agrupando por la columna screen
               return columns.frame("episode", rows)

3. ``find`` devuelve un DataFrame con las columnas de la tabla ``episode``
   (``type``, ``t_start``, ``t_end``, ``screen``, ``outcome``, ``metrics``),
   todas con ``type`` igual a su ``episode_type``. ``metrics`` es un
   diccionario con las métricas propias del tipo. Sin episodios, devuelve
   ``columns.empty("episode")``.
4. Lee los umbrales de ``params``, nunca escritos en el código.
5. Prueba el detector con un caso que debe reconocer y uno que no.

Un detector no modifica ``data``. Si falla o devuelve columnas incorrectas, la
etapa se detiene con un error que lo nombra.
"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from analysis import columns, detectors
from analysis.loader import SessionData
from analysis.parameters import Parameters
from analysis.registry import Registry
from shared import contracts


class EpisodeDetector(Protocol):
    """Interfaz de un detector de episodios.

    Attributes:
        episode_type: Tipo de episodio que reconoce (``episode_type``).
    """

    episode_type: str

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Reconoce los episodios de su tipo en una sesión.

        Args:
            data: Datos de la sesión, limpios y con pantallas.
            params: Parámetros del análisis.

        Returns:
            DataFrame con las columnas de ``episode``; vacío si no hay ninguno.
        """
        ...


EPISODE_DETECTORS: Registry[EpisodeDetector] = Registry(
    "episode detector", key="episode_type", allowed=contracts.enums()["episode_type"]
)
"""Detectores de episodios registrados."""


def detect(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Ejecuta todos los detectores de episodios registrados y une sus episodios.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        params: Parámetros del análisis.

    Returns:
        Episodios de todos los detectores, ordenados por inicio, con las
        columnas de ``episode``. Vacío si no hay detectores o episodios.

    Raises:
        RuntimeError: Si un detector falla; el mensaje lo nombra.
        columns.ColumnValidationError: Si un detector devuelve columnas,
            tipos o un ``type`` incorrectos.
    """
    found = []
    for detector in EPISODE_DETECTORS.all():
        label = f"episode detector {detector.episode_type}"
        try:
            result = detector.find(data, params)
        except Exception as error:
            raise RuntimeError(f"{label} failed: {error}") from error
        columns.validate(result, "episode", label=label)
        other_types = sorted(set(result["type"]) - {detector.episode_type})
        if other_types:
            raise columns.ColumnValidationError(
                label, "episode", [f"returned episodes of other types: {other_types}"]
            )
        found.append(result)
    return columns.concat("episode", found).sort_values("t_start", kind="stable", ignore_index=True)


@dataclass
class _Visit:
    """Una visita continua a una pantalla, con sus eventos observados."""

    screen: str
    start: float
    end: float
    events: list[Any]
    exited: bool = False
    exit_click: float | None = None


@dataclass
class _FormRun:
    """Interacciones de un formulario dentro de una visita."""

    visit: _Visit
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
            if event.type == "form_submit" or event.type != "focus_out" and _is_field(event.element)
        )


def _visits(data: SessionData) -> list[_Visit]:
    """Separa visitas por cambios de pantalla y excluye los huecos de cámara."""
    visits: list[_Visit] = []
    navigated_clicks = set()
    for event in data.events[data.events["type"] != "camera_gap"].itertuples():
        if (
            event.type == "click_response"
            and isinstance(event.data, dict)
            and event.data.get("navigated")
        ):
            navigated_clicks.add(event.data["click_t"])
        if not visits or event.screen != visits[-1].screen:
            if visits:
                visits[-1].end = event.t
                visits[-1].exited = True
            visits.append(_Visit(event.screen, event.t, event.t, []))
        visits[-1].events.append(event)
        visits[-1].end = event.t
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


def _is_field(element: Any) -> bool:
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


def _form_runs(data: SessionData) -> list[_FormRun]:
    """Agrupa interacciones observables sin mezclar visitas ni formularios conocidos."""
    runs = []
    for visit in _visits(data):
        forms = {
            event.element["selector"]: event.element
            for event in visit.events
            if event.type == "form_submit" and isinstance(event.element, dict)
        }
        groups: dict[str, _FormRun] = {}
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
            if event.type != "form_submit" and not _is_field(element):
                if event.type != "click" or owner is None:
                    continue
            key = owner or ("__search__" if _is_search(element) else "__fields__")
            previous = groups.get(key)
            if (
                previous is not None
                and _is_field(element)
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
            groups.setdefault(key, _FormRun(visit)).events.append(event)
        runs.extend(
            run
            for run in groups.values()
            if any(
                event.type == "form_submit"
                or event.type != "focus_out"
                and _is_field(event.element)
                for event in run.events
            )
        )
    return sorted(runs, key=lambda run: run.start)


def _metrics(run: _FormRun) -> tuple[int, int, int]:
    """Cuenta envíos lógicos, errores y reingresos con cambios tras recuperar foco."""
    attempts = errors = reentries = 0
    filled: set[str] = set()
    focused = None
    pending_reentry = pending_submit = False
    for event in run.events:
        key = event.element["selector"]
        if event.type == "form_submit":
            if not pending_submit:
                attempts += 1
            pending_submit, focused = True, None
        elif event.type == "validation_error":
            errors += 1
            pending_submit = False
        elif _is_field(event.element):
            if event.type == "focus_out":
                focused, pending_reentry = None, False
            elif event.type in ("click", "focus_in", "field_change"):
                if focused != key:
                    focused, pending_reentry = key, key in filled
                if event.type == "field_change":
                    reentries += int(pending_reentry)
                    pending_reentry, pending_submit = False, False
                    filled.add(key)
    return attempts, errors, reentries


def _exit_time(run: _FormRun) -> float:
    """Usa un clic con navegación confirmada o el fin observado de la visita."""
    click = run.visit.exit_click
    return click if click is not None and click >= run.start else run.visit.end


def _form_rows(data: SessionData, kind: str) -> pd.DataFrame:
    """Produce episodios de formulario o autenticación con sus métricas."""
    rows = []
    for run in _form_runs(data):
        if run.kind != kind:
            continue
        attempts, errors, reentries = _metrics(run)
        submissions = [event.t for event in run.events if event.type == "form_submit"]
        signals = [
            event.type for event in run.events if event.type in ("form_submit", "validation_error")
        ]
        submitted = bool(signals) and signals[-1] == "form_submit"
        outcome = "submitted" if submitted else "abandoned"
        if kind == "login":
            outcome = (
                "success"
                if submitted and run.visit.exited
                else ("submitted" if submitted else "failed" if attempts else "abandoned")
            )
        rows.append(
            {
                "type": kind,
                "t_start": run.start,
                "t_end": submissions[-1] if submitted else _exit_time(run),
                "screen": run.visit.screen,
                "outcome": outcome,
                "metrics": {"attempts": attempts, "errors": errors}
                if kind == "login"
                else {"errors": errors, "reentries": reentries},
            }
        )
    return columns.frame("episode", rows)


def _result_link(element: Any) -> bool:
    """Reconoce enlaces candidatos a resultado, excluyendo navegación identificable."""
    if not isinstance(element, dict) or not (
        element.get("tag") == "a" or element.get("role") == "link"
    ):
        return False
    identity = f"{element.get('id') or ''} {element.get('selector', '')}"
    return element.get("role") != "menuitem" and not re.search(
        r"(?<![a-z0-9])(nav|menu|header|footer|back|home)(?![a-z0-9])", identity, re.I
    )


def _search_rows(data: SessionData) -> pd.DataFrame:
    """Une reformulaciones hasta abrir un resultado, salir o cambiar de actividad."""
    events = list(data.events[data.events["type"] != "camera_gap"].itertuples())
    times = [event.t for event in events]
    responses = {
        event.data["click_t"]: event
        for event in events
        if event.type == "click_response" and isinstance(event.data, dict)
    }
    runs = _form_runs(data)
    rows = []
    active = None
    result_screen = ""
    for index, run in enumerate(runs):
        if run.kind != "search":
            if active is not None:
                rows.append(active)
                active = None
            continue
        submits = [event for event in run.events if event.type == "form_submit"]
        if not submits:
            continue
        if active is not None and run.visit.screen != result_screen:
            rows.append(active)
            active = None
        if active is None:
            active = {
                "type": "search",
                "t_start": run.start,
                "t_end": submits[-1].t,
                "screen": run.visit.screen,
                "outcome": "no_result_opened",
                "metrics": {"searches": 0, "result_clicks": 0},
            }
        active["metrics"]["searches"] += _metrics(run)[0]
        clicks = [
            event.t
            for event in run.events
            if event.type == "click" and not _is_field(event.element) and event.t <= submits[-1].t
        ]
        response = responses.get(clicks[-1]) if clicks else None
        active["t_end"] = response.t if response is not None else submits[-1].t
        result_screen = response.screen if response is not None else run.visit.screen
        stop = runs[index + 1].start if index + 1 < len(runs) else float("inf")
        start_index, stop_index = bisect_right(times, active["t_end"]), bisect_left(times, stop)
        for event in events[start_index:stop_index]:
            if (
                event.type == "click"
                and event.screen == result_screen
                and _result_link(event.element)
            ):
                active["t_end"] = event.t
                active["outcome"] = "result_opened"
                active["metrics"]["result_clicks"] = 1
                rows.append(active)
                active = None
                break
            if event.screen != result_screen:
                rows.append(active)
                active = None
                break
    if active is not None:
        rows.append(active)
    return columns.frame("episode", rows)


@EPISODE_DETECTORS.register
class LoginEpisodes:
    """Episodios de autenticación reconocibles en los eventos capturados."""

    episode_type = "login"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Devuelve intentos, errores y resultado de cada interacción de autenticación."""
        return _form_rows(data, self.episode_type)


@EPISODE_DETECTORS.register
class FormEpisodes:
    """Episodios de llenado, envío o abandono de formularios."""

    episode_type = "form"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Devuelve formularios con sus errores y reingresos."""
        return _form_rows(data, self.episode_type)


@EPISODE_DETECTORS.register
class SearchEpisodes:
    """Búsquedas y reformulaciones hasta abrir un resultado o abandonar."""

    episode_type = "search"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Devuelve búsquedas, clics en resultados y sus intervalos."""
        return _search_rows(data)


@EPISODE_DETECTORS.register
class ScreenEpisodes:
    """Visitas continuas a pantallas normalizadas."""

    episode_type = "screen"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Cuenta los incidentes registrados que comienzan dentro de cada visita."""
        visits = _visits(data)
        if not visits:
            return columns.empty("episode")
        by_screen: dict[str, list[float]] = {}
        for incident in detectors.detect(data, params).itertuples():
            by_screen.setdefault(incident.screen, []).append(incident.t)
        for times in by_screen.values():
            times.sort()
        rows = []
        for visit in visits:
            times = by_screen.get(visit.screen, [])
            rows.append(
                {
                    "type": self.episode_type,
                    "t_start": visit.start,
                    "t_end": visit.end,
                    "screen": visit.screen,
                    "metrics": {
                        "incidents": bisect_left(times, visit.end) - bisect_left(times, visit.start)
                    },
                }
            )
        return columns.frame("episode", rows)
