"""Guardado de sesiones simuladas en una base, por el mismo camino que los datos reales.

No hay SQL propio para las sesiones: se usan las funciones del servidor
(``create_session``, ``store_batch``, ``save_sus``, ``close_session``,
``create_reference``), que validan cada registro con los contratos y lo guardan
como si llegara de la extensión. Los resultados esperados se guardan con el
repositorio del análisis, y las referencias se confirman con la misma función
que el panel de resultados. Lo único propio es guardar los pasos y las
candidatas de una referencia, que en el sistema real extrae el análisis; se
valida con ``reference.schema.json``.

Para las pruebas del análisis::

    connection = create_database(tmp_path / "test.db")
    builder = SessionBuilder(study_id=1, mode="free").on_screen(HOME)
    session = builder.with_rage_click(BUTTON).build()
    data = load_session(connection, session)   # SessionData, listo para una etapa
"""

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from analysis import columns
from analysis.loader import SessionData, SqliteAnalysisRepository
from dashboard.data import DashboardData
from scripts.init_db import init_db
from scripts.load_study import LoadedStudy, load_study, read_study
from scripts.simulation.builder import ReferenceRecording, SessionTruth, SimulatedSession
from server import services
from server.repositories import SqliteRepository, to_json
from shared import contracts, db
from shared.config import ROOT_DIR, load_config

EXAMPLE_STUDY = ROOT_DIR / "studies" / "example.yaml"
"""Estudio de los datos simulados."""


class StoreError(ValueError):
    """Una referencia simulada no cumple su contrato."""


def create_database(path: Path, study_file: Path = EXAMPLE_STUDY) -> sqlite3.Connection:
    """Crea una base vacía (o la recrea) con el esquema y un estudio cargado.

    Args:
        path: Archivo de la base; si existe, se borra.
        study_file: Estudio a cargar; por defecto, el de ejemplo.

    Returns:
        Conexión abierta. Quien la abre la cierra.
    """
    init_db(path, reset=True)
    connection = db.open_database(path)
    load_study(connection, read_study(study_file))
    return connection


def load_example_study(connection: sqlite3.Connection) -> LoadedStudy:
    """Devuelve los id del estudio de ejemplo ya cargado (cargarlo de nuevo no duplica).

    Args:
        connection: Conexión a la base.

    Returns:
        Id del estudio y de sus tareas.
    """
    return load_study(connection, read_study(EXAMPLE_STUDY))


def store_session(connection: sqlite3.Connection, session: SimulatedSession) -> int:
    """Guarda una sesión simulada como si llegara de la extensión.

    Crea la sesión, envía sus lotes de a ``sending.max_batch_records``
    registros, guarda el SUS y la cierra, con las marcas de tiempo simuladas.

    Args:
        connection: Conexión a una base con el estudio cargado.
        session: Sesión simulada.

    Returns:
        Id de la sesión creada.

    Raises:
        services.InvalidRequestError: Si algún registro no cumple su contrato.
    """
    repository = _server_repository(connection)
    created = services.create_session(
        session.request, studies=repository, sessions=repository, now=lambda: session.started_at
    )
    session_id = created["session_id"]
    size = load_config().sending.max_batch_records
    for batch_type, records in session.batches.items():
        for chunk in _chunks(records, size):
            services.store_batch(
                session_id,
                {
                    "contract_version": contracts.contract_version(),
                    "type": batch_type,
                    "records": chunk,
                },
                sessions=repository,
                studies=repository,
                writer=repository,
            )
    if session.sus_answers is not None:
        services.save_sus(session_id, {"answers": list(session.sus_answers)}, sessions=repository)
    services.close_session(session_id, sessions=repository, now=lambda: session.ended_at)
    return session_id


def store_references(
    connection: sqlite3.Connection,
    session_id: int,
    recordings: Sequence[ReferenceRecording],
    conditions: Mapping[int, tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]],
) -> dict[int, int]:
    """Guarda y confirma las referencias grabadas en una sesión de modo ``reference``.

    Cada una se crea en borrador con ``create_reference`` (como lo haría el
    panel lateral) y se confirma con sus pasos, candidatas, condición final y
    pasos obligatorios (como lo harían el análisis y el panel de resultados).

    Args:
        connection: Conexión a la base.
        session_id: Sesión de modo ``reference`` ya guardada.
        recordings: Grabaciones de esa sesión.
        conditions: Por tarea, su condición final confirmada y sus candidatas.

    Returns:
        Id de la referencia de cada tarea.

    Raises:
        StoreError: Si una referencia no cumple ``reference.schema.json``.
    """
    repository = _server_repository(connection)
    created = {}
    for recording in recordings:
        end_condition, candidates = conditions[recording.task_id]
        reference_id = services.create_reference(
            {"task_id": recording.task_id, "source_session_id": session_id},
            sessions=repository,
            studies=repository,
            references=repository,
        )["reference_id"]
        confirm_reference(
            connection,
            reference_id,
            steps=recording.steps,
            candidates=[end_condition, *candidates],
            end_condition=end_condition,
            required_steps=recording.required_steps,
            duration_ms=recording.duration_ms,
        )
        created[recording.task_id] = reference_id
    return created


def confirm_reference(
    connection: sqlite3.Connection,
    reference_id: int,
    *,
    steps: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    end_condition: Mapping[str, Any],
    required_steps: Sequence[int],
    duration_ms: float,
) -> None:
    """Completa una referencia en borrador y la confirma.

    Primero guarda lo que en el sistema real extrae el análisis (pasos,
    candidatas y duración); después la confirma con la misma función que usa
    el panel de resultados, que valida la referencia completa con su contrato.

    Args:
        connection: Conexión a la base.
        reference_id: Referencia en borrador.
        steps: Pasos de la ruta.
        candidates: Condiciones finales propuestas.
        end_condition: Condición final confirmada.
        required_steps: Posiciones de los pasos obligatorios.
        duration_ms: Duración de la grabación.

    Raises:
        StoreError: Si los pasos o las candidatas no cumplen ``reference.schema.json``.
        dashboard.data.InvalidReferenceError: Si la condición o los pasos
            obligatorios no lo cumplen.
    """
    draft = {
        "steps": list(steps),
        "candidates": list(candidates),
        "end_condition": None,
        "required_steps": [],
    }
    errors = contracts.validate("reference", draft)
    if errors:
        raise StoreError(f"reference {reference_id} does not match its contract: {errors[0]}")
    with db.transaction(connection):
        connection.execute(
            "UPDATE reference SET steps = ?, candidates = ?, duration_ms = ? WHERE id = ?",
            (to_json(draft["steps"]), to_json(draft["candidates"]), duration_ms, reference_id),
        )
    DashboardData(connection, _data_dir(connection)).confirm_reference(
        reference_id, dict(end_condition), list(required_steps)
    )


def store_expected_results(
    connection: sqlite3.Connection, session_id: int, truth: SessionTruth, params_version: str
) -> None:
    """Llena las tablas de resultados de una sesión con su verdad de referencia.

    Usa el repositorio del análisis, así los resultados quedan como si los
    hubiera calculado el pipeline.

    Args:
        connection: Conexión a la base.
        session_id: Sesión ya guardada.
        truth: Verdad de referencia de la sesión.
        params_version: Versión que se guarda con el índice.
    """
    frames = result_frames(truth)
    SqliteAnalysisRepository(connection).save_results(
        session_id, **frames, params_version=params_version
    )


def result_frames(truth: SessionTruth) -> dict[str, Any]:
    """Convierte una verdad de referencia en los DataFrames de las tablas de resultados.

    Cada incidente usa su tiempo de referencia (``ExpectedIncident.t``).

    Args:
        truth: Verdad de referencia.

    Returns:
        ``episodes``, ``incidents``, ``task_results`` y ``usability_index``.
    """
    index = truth.usability_index
    return {
        "episodes": columns.frame(
            "episode",
            [
                {
                    "type": item.type,
                    "t_start": item.t_start,
                    "t_end": item.t_end,
                    "screen": item.screen,
                    "outcome": item.outcome,
                    "metrics": dict(item.metrics),
                }
                for item in truth.episodes
            ],
        ),
        "incidents": columns.frame(
            "incident",
            [
                {
                    "type": item.type,
                    "t": item.t,
                    "screen": item.screen,
                    "task_id": item.task_id,
                    "element": None if item.element is None else dict(item.element),
                }
                for item in truth.incidents
            ],
        ),
        "task_results": columns.frame(
            "task_result",
            [
                {
                    "task_id": item.task_id,
                    "success": item.success,
                    "duration_ms": item.duration_ms,
                    "steps": item.steps,
                    "deviation_step": item.deviation_step,
                    "off_path_ms": item.off_path_ms,
                }
                for item in truth.tasks
            ],
        ),
        "usability_index": columns.frame(
            "usability_index",
            [] if index is None else [{name: getattr(index, name) for name in _INDEX_FIELDS}],
        ),
    }


def load_session(connection: sqlite3.Connection, session: SimulatedSession) -> SessionData:
    """Guarda una sesión simulada y la carga como la recibe el análisis.

    Args:
        connection: Conexión a una base con el estudio cargado (``create_database``).
        session: Sesión simulada.

    Returns:
        Datos de la sesión, listos para pasarlos a una etapa.
    """
    return SqliteAnalysisRepository(connection).load_session(store_session(connection, session))


_INDEX_FIELDS = ("effectiveness", "time_efficiency", "path_efficiency", "friction", "bui")


def _server_repository(connection: sqlite3.Connection) -> SqliteRepository:
    """Repositorio del servidor sobre la misma conexión; las simulaciones no guardan capturas."""
    return SqliteRepository(connection, _data_dir(connection))


def _data_dir(connection: sqlite3.Connection) -> Path:
    """Carpeta de la base abierta en la conexión."""
    return Path(connection.execute("PRAGMA database_list").fetchone()[2]).parent


def _chunks(records: Sequence[Mapping[str, Any]], size: int) -> Iterator[list[Mapping[str, Any]]]:
    """Parte los registros en lotes de a lo sumo ``size``."""
    for start in range(0, len(records), size):
        yield list(records[start : start + size])
