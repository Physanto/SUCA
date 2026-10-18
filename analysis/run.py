"""Orquestador del análisis (Pipeline) y su línea de comandos.

Analiza una sesión terminada en seis etapas con nombre, cada una con una firma
fija:

1. ``cleaning``: ``cleaning.clean(data, params)`` → datos limpios;
2. ``screens``: ``screens.assign_screens(data, params)`` → datos con pantallas;
3. ``episodes``: ``episodes.detect(data, params)`` → tabla ``episode``;
4. ``detectors``: ``detectors.detect(data, params)`` → tabla ``incident``;
5. ``reference``: ``reference.compare(data, params)`` → tabla ``task_result``;
6. ``usability_index``: ``usability_index.compute(data, task_results,
   incidents, params)`` → tabla ``usability_index``.

A la salida de cada etapa se validan las columnas (``analysis/columns.py``) y
se registra cuánto tardó. Si una etapa falla, el análisis de esa sesión se
detiene con un mensaje que nombra la etapa y no se guarda nada. Al final, el
repositorio reemplaza los resultados previos de la sesión.

Es el punto de composición del análisis: aquí se arman los parámetros, la
conexión y el repositorio.

Uso::

    python -m analysis.run --session 17
    python -m analysis.run --study 2
    python -m analysis.run --session 17 --db data/mock.db
"""

import argparse
import logging
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from analysis import cleaning, columns, detectors, episodes, reference, screens, usability_index
from analysis.loader import (
    AnalysisRepository,
    NotFoundError,
    SessionData,
    SqliteAnalysisRepository,
    validate_session_data,
)
from analysis.parameters import Parameters, ParametersError, load_parameters
from shared import db
from shared.config import ConfigError, load_config

logger = logging.getLogger("analysis")


@dataclass(frozen=True)
class AnalysisResults:
    """Estado del análisis de una sesión: los datos y lo que produjo cada etapa.

    Attributes:
        data: Datos de la sesión, tal como los dejaron las dos primeras etapas.
        episodes: Episodios (tabla ``episode``).
        incidents: Incidentes (tabla ``incident``).
        task_results: Resultados por tarea (tabla ``task_result``).
        usability_index: Índice de la sesión (tabla ``usability_index``).
        timings_ms: Duración de cada etapa ejecutada, en milisegundos y en orden.
    """

    data: SessionData
    episodes: pd.DataFrame
    incidents: pd.DataFrame
    task_results: pd.DataFrame
    usability_index: pd.DataFrame
    timings_ms: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Stage:
    """Una etapa del pipeline.

    Attributes:
        name: Nombre de la etapa, para los registros y los errores.
        output: Campo de ``AnalysisResults`` que llena.
        run: Recibe el estado y los parámetros y devuelve el valor de ``output``.
        check: Valida ese valor; lanza un error si no es correcto.
    """

    name: str
    output: str
    run: Callable[[AnalysisResults, Parameters], Any]
    check: Callable[[Any], None]


class StageError(RuntimeError):
    """Una etapa falló o devolvió datos incorrectos.

    Attributes:
        stage: Nombre de la etapa.
    """

    def __init__(self, stage: str, error: Exception) -> None:
        """Arma el mensaje con la etapa y la causa.

        Args:
            stage: Nombre de la etapa.
            error: Error original.
        """
        self.stage = stage
        super().__init__(f"stage {stage!r} failed: {error}")


def _table_check(table: str) -> Callable[[Any], None]:
    """Devuelve la validación de la salida de una etapa contra una tabla."""
    return lambda value: columns.validate(value, table)


# Cada etapa llama a su módulo en el momento de ejecutarse (no al importar este
# archivo), así las pruebas pueden sustituir una etapa.
STAGES: tuple[Stage, ...] = (
    Stage(
        "cleaning",
        "data",
        lambda state, params: cleaning.clean(state.data, params),
        validate_session_data,
    ),
    Stage(
        "screens",
        "data",
        lambda state, params: screens.assign_screens(state.data, params),
        validate_session_data,
    ),
    Stage(
        "episodes",
        "episodes",
        lambda state, params: episodes.detect(state.data, params),
        _table_check("episode"),
    ),
    Stage(
        "detectors",
        "incidents",
        lambda state, params: detectors.detect(state.data, params),
        _table_check("incident"),
    ),
    Stage(
        "reference",
        "task_results",
        lambda state, params: reference.compare(state.data, params),
        _table_check("task_result"),
    ),
    Stage(
        "usability_index",
        "usability_index",
        lambda state, params: usability_index.compute(
            state.data, state.task_results, state.incidents, params
        ),
        _table_check("usability_index"),
    ),
)
"""Etapas del análisis, en orden."""


def run_pipeline(
    data: SessionData, params: Parameters, stages: tuple[Stage, ...] = STAGES
) -> AnalysisResults:
    """Ejecuta las etapas sobre los datos de una sesión, sin tocar la base.

    Args:
        data: Datos de la sesión.
        params: Parámetros del análisis.
        stages: Etapas a ejecutar, en orden.

    Returns:
        Lo que produjo cada etapa y cuánto tardó.

    Raises:
        StageError: Si una etapa falla o devuelve datos incorrectos.
    """
    state = AnalysisResults(
        data=data,
        episodes=columns.empty("episode"),
        incidents=columns.empty("incident"),
        task_results=columns.empty("task_result"),
        usability_index=columns.empty("usability_index"),
    )
    timings: dict[str, float] = {}
    for stage in stages:
        started = time.perf_counter()
        try:
            value = stage.run(state, params)
            stage.check(value)
        except Exception as error:
            raise StageError(stage.name, error) from error
        timings[stage.name] = (time.perf_counter() - started) * 1000
        logger.info("session %d: %s took %.1f ms", data.session.id, stage.name, timings[stage.name])
        state = replace(state, **{stage.output: value})
    return replace(state, timings_ms=MappingProxyType(timings))


def analyze_session(
    repository: AnalysisRepository, session_id: int, params: Parameters
) -> AnalysisResults:
    """Analiza una sesión y reemplaza sus resultados en la base.

    Args:
        repository: Acceso a la base del análisis.
        session_id: Sesión a analizar.
        params: Parámetros del análisis.

    Returns:
        Resultados de la sesión.

    Raises:
        NotFoundError: Si la sesión no existe.
        StageError: Si una etapa falla; en ese caso no se guarda nada.
    """
    data = repository.load_session(session_id)
    if not data.session.closed:
        logger.warning("session %d is still open: its data may be incomplete", session_id)
    results = run_pipeline(data, params)
    repository.save_results(
        session_id,
        results.episodes,
        results.incidents,
        results.task_results,
        results.usability_index,
        params.version,
    )
    return results


def summary(results: AnalysisResults) -> str:
    """Resume en una línea los resultados de una sesión.

    Args:
        results: Resultados de la sesión.

    Returns:
        Por ejemplo, ``session 17: 2 episodes, 5 incidents, 4 task results, bui 71.3 (12.4 ms)``.
    """
    index = results.usability_index
    bui = f"bui {index['bui'].iloc[0]:.1f}" if len(index) else "no index"
    return (
        f"session {results.data.session.id}: {len(results.episodes)} episodes, "
        f"{len(results.incidents)} incidents, {len(results.task_results)} task results, "
        f"{bui} ({sum(results.timings_ms.values()):.1f} ms)"
    )


def _sessions_to_analyze(repository: AnalysisRepository, args: argparse.Namespace) -> list[int]:
    """Decide qué sesiones analizar: la pedida, o las cerradas del estudio."""
    if args.session is not None:
        return [args.session]
    sessions = repository.list_sessions(args.study)
    for session in sessions:
        if not session.closed:
            print(f"session {session.id}: skipped (still open)")
    closed = [session.id for session in sessions if session.closed]
    if not closed:
        print(f"study {args.study}: no closed sessions to analyze")
    return closed


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si todo se analizó, 1 si algo falló.
    """
    parser = argparse.ArgumentParser(
        prog="python -m analysis.run",
        description="Analiza sesiones terminadas y guarda sus resultados.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--session", type=int, metavar="ID", help="analiza una sesión")
    target.add_argument(
        "--study", type=int, metavar="ID", help="analiza las sesiones cerradas de un estudio"
    )
    parser.add_argument(
        "--db", type=Path, help="ruta de la base (por defecto, database.path de la configuración)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        params = load_parameters()
        connection = db.open_database(args.db or load_config().database.path)
    except (ParametersError, ConfigError, FileNotFoundError, db.SchemaVersionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    with closing(connection):
        repository = SqliteAnalysisRepository(connection)
        try:
            session_ids = _sessions_to_analyze(repository, args)
        except NotFoundError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        failures = 0
        for session_id in session_ids:
            try:
                print(summary(analyze_session(repository, session_id, params)))
            except Exception as error:
                # Una sesión que falla no impide analizar las demás del estudio.
                print(f"error: session {session_id}: {error}", file=sys.stderr)
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
