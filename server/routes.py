"""Endpoints HTTP del servidor.

Cada endpoint solo traduce HTTP: toma los datos de la petición, llama a una
función de ``services`` y devuelve su resultado. No contiene reglas.
"""

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


@router.get("/health")
def get_health() -> dict[str, str]:
    """Comprueba que el servidor está activo."""
    return services.health()


@router.post("/sessions/{session_id}/batches")
def post_batch(
    session_id: int,
    body: Annotated[Any, Body()],
    repository: Annotated[Repository, Depends(get_repository)],
) -> dict[str, int]:
    """Recibe un lote de cualquier tipo y lo guarda completo o nada."""
    return services.store_batch(
        session_id, body, sessions=repository, studies=repository, writer=repository
    )
