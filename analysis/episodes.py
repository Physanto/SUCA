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

from bisect import bisect_left
from typing import Protocol

import pandas as pd

from analysis import columns, detectors
from analysis.form_activity import (
    form_exit_time,
    form_metrics,
    form_runs,
    search_activities,
    visits,
)
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


def _form_rows(data: SessionData, kind: str) -> pd.DataFrame:
    """Produce episodios de formulario o autenticación con sus métricas."""
    rows = []
    runs = form_runs(data)
    for run in runs:
        if run.kind != kind:
            continue
        attempts, errors, reentries = form_metrics(run)
        submissions = [event.t for event in run.events if event.type == "form_submit"]
        signals = [
            event.type for event in run.events if event.type in ("form_submit", "validation_error")
        ]
        submitted = bool(signals) and signals[-1] == "form_submit"
        outcome = "submitted" if submitted else "abandoned"
        if kind == "login":
            # Si vuelve a intentarlo sin salir de la pantalla, este intento no dio acceso.
            retried = any(
                other is not run
                and other.kind == kind
                and other.visit is run.visit
                and other.start > run.start
                for other in runs
            )
            outcome = (
                "failed"
                if submitted and retried
                else "success"
                if submitted and run.visit.exited
                else ("submitted" if submitted else "failed" if attempts else "abandoned")
            )
        rows.append(
            {
                "type": kind,
                "t_start": run.start,
                "t_end": submissions[-1] if submitted else form_exit_time(run),
                "screen": run.visit.screen,
                "outcome": outcome,
                "metrics": {"attempts": attempts, "errors": errors}
                if kind == "login"
                else {"errors": errors, "reentries": reentries},
            }
        )
    return columns.frame("episode", rows)


def _search_rows(data: SessionData) -> pd.DataFrame:
    """Une reformulaciones hasta abrir un resultado, salir o cambiar de actividad."""
    return columns.frame(
        "episode",
        [
            {
                "type": "search",
                "t_start": activity.runs[0].start,
                "t_end": activity.end,
                "screen": activity.runs[0].visit.screen,
                "outcome": "result_opened"
                if activity.result_click is not None
                else "no_result_opened",
                "metrics": {
                    "searches": sum(form_metrics(run)[0] for run in activity.runs),
                    "result_clicks": int(activity.result_click is not None),
                },
            }
            for activity in search_activities(data)
        ],
    )


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
        page_visits = visits(data)
        if not page_visits:
            return columns.empty("episode")
        by_screen: dict[str, list[float]] = {}
        for incident in detectors.detect(data, params).itertuples():
            by_screen.setdefault(incident.screen, []).append(incident.t)
        for times in by_screen.values():
            times.sort()
        rows = []
        for visit in page_visits:
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
