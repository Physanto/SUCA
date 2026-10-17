"""Casos de uso del servidor: validan, aplican las reglas y usan los repositorios.

Cada función recibe solo las interfaces que necesita y no sabe de HTTP: informa
los problemas con las excepciones de este módulo, que ``app.py`` traduce a
códigos de estado. Son funciones y no clases porque no guardan estado.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from shared import contracts, db


@dataclass(frozen=True)
class ErrorItem:
    """Un problema concreto de una petición.

    Attributes:
        record: Posición del registro dentro del lote, o ``None`` si el problema
            no es de un registro.
        field: Ruta del campo con el problema (por ejemplo ``x`` o
            ``screen/url``). Vacía si el problema es del documento completo.
        message: Motivo, en inglés.
    """

    record: int | None
    field: str
    message: str


class NotFoundError(Exception):
    """No existe el recurso indicado en la ruta de la petición."""


class ConflictError(Exception):
    """La petición choca con el estado actual, por ejemplo una sesión cerrada."""


class InvalidRequestError(Exception):
    """El cuerpo de la petición no cumple su contrato o nombra algo que no existe.

    Attributes:
        errors: Problemas encontrados.
    """

    def __init__(self, message: str, errors: Sequence[ErrorItem]) -> None:
        """Crea el error.

        Args:
            message: Resumen del problema.
            errors: Problemas encontrados, al menos uno.
        """
        super().__init__(message)
        self.errors = tuple(errors)


def health() -> dict[str, str]:
    """Informa que el servidor está activo y con qué versiones trabaja.

    Returns:
        Estado, versión de los contratos y versión del esquema de la base.
    """
    return {
        "status": "ok",
        "contract_version": contracts.contract_version(),
        "schema_version": db.expected_schema_version(),
    }
