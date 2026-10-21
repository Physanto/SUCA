"""Endpoints HTTP del servidor.

Cada endpoint solo traduce HTTP: toma los datos de la petición, llama a una
función de ``services`` y devuelve su resultado. No contiene reglas.
"""

import time
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request

from server import services
from server.repositories import Repository

router = APIRouter()


def get_repository(request: Request) -> Iterator[Repository]:
    """Dependencia: repositorio de la petición, sobre una conexión propia.

    La app define cómo se abre (``app.state.open_repository``); las pruebas
    pueden sustituir esta dependencia con ``dependency_overrides``.
    """
    with request.app.state.open_repository() as repository:
        yield repository


def current_time_ms() -> float:
    """Devuelve el momento actual en milisegundos desde 1970."""
    return time.time() * 1000


def get_clock() -> services.Clock:
    """Dependencia: reloj del servidor. Las pruebas lo sustituyen por uno fijo."""
    return current_time_ms


Repo = Annotated[Repository, Depends(get_repository)]
Clock = Annotated[services.Clock, Depends(get_clock)]
JsonBody = Annotated[Any, Body()]


@router.get("/health")
def get_health() -> dict[str, str]:
    """Comprueba que el servidor está activo."""
    return services.health()


@router.get("/studies")
def get_studies(repository: Repo) -> list[dict[str, Any]]:
    """Lista los estudios."""
    return services.list_studies(studies=repository)


@router.get("/studies/{study_id}/tasks")
def get_study_tasks(study_id: int, repository: Repo) -> list[dict[str, Any]]:
    """Lista las tareas de un estudio con sus referencias confirmadas."""
    return services.list_tasks(study_id, studies=repository)


@router.post("/sessions", status_code=201)
def post_session(body: JsonBody, repository: Repo, now: Clock) -> dict[str, Any]:
    """Crea una sesión."""
    return services.create_session(body, studies=repository, sessions=repository, now=now)


@router.post("/sessions/{session_id}/sus")
def post_sus(session_id: int, body: JsonBody, repository: Repo) -> dict[str, float]:
    """Guarda las respuestas del SUS de una sesión."""
    return services.save_sus(session_id, body, sessions=repository)


@router.post("/sessions/{session_id}/close")
def post_close(session_id: int, repository: Repo, now: Clock) -> dict[str, Any]:
    """Cierra una sesión."""
    return services.close_session(session_id, sessions=repository, now=now)


@router.post("/references", status_code=201)
def post_reference(body: JsonBody, repository: Repo) -> dict[str, int]:
    """Guarda en borrador una referencia grabada."""
    return services.create_reference(
        body, sessions=repository, studies=repository, references=repository
    )


@router.post("/sessions/{session_id}/batches")
def post_batch(session_id: int, body: JsonBody, repository: Repo) -> dict[str, int]:
    """Recibe un lote de cualquier tipo y lo guarda completo o nada."""
    return services.store_batch(
        session_id, body, sessions=repository, studies=repository, writer=repository
    )


@router.post("/captures", status_code=201)
def post_capture(body: JsonBody, repository: Repo, now: Clock) -> dict[str, Any]:
    """Guarda una captura de pantalla de referencia."""
    return services.save_capture(body, studies=repository, captures=repository, now=now)
