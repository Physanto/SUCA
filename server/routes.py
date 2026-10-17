"""Endpoints HTTP del servidor.

Cada endpoint solo traduce HTTP: toma los datos de la petición, llama a una
función de ``services`` y devuelve su resultado. No contiene reglas.
"""

from fastapi import APIRouter

from server import services

router = APIRouter()


@router.get("/health")
def get_health() -> dict[str, str]:
    """Comprueba que el servidor está activo."""
    return services.health()
