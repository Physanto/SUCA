"""Casos de uso del servidor: validan, aplican las reglas y usan los repositorios.

Cada función recibe solo las interfaces que necesita y no sabe de HTTP: informa
los problemas con las excepciones de este módulo, que ``app.py`` traduce a
códigos de estado. Son funciones y no clases porque no guardan estado.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from server import ingestion
from server.repositories import BatchWriter, SessionInfo, SessionStore, StudyReader
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


def store_batch(
    session_id: int,
    body: Any,
    *,
    sessions: SessionStore,
    studies: StudyReader,
    writer: BatchWriter,
) -> dict[str, int]:
    """Valida un lote y guarda todos sus registros, o ninguno.

    Comprueba, en orden: que la sesión exista y esté abierta, que la versión de
    los contratos sea compatible, que el lote cumpla su contrato y que cada
    ``task_id`` sea del estudio de la sesión.

    Args:
        session_id: Sesión de la ruta.
        body: Lote decodificado desde JSON.
        sessions: Consulta de sesiones.
        studies: Consulta de tareas del estudio.
        writer: Escritura de los registros.

    Returns:
        Cantidad de registros guardados.

    Raises:
        NotFoundError: Si la sesión no existe.
        ConflictError: Si la sesión está cerrada.
        InvalidRequestError: Si el lote no es compatible o no cumple el contrato.
    """
    session = _open_session(sessions, session_id)
    _check_contract_version(body)
    _validate("batch", body, "batch does not match its contract")
    records = body["records"]

    known_tasks = studies.task_ids(session.study_id)
    foreign = [
        ErrorItem(
            record=index,
            field="task_id",
            message=f"task {record['task_id']} does not belong to study {session.study_id}",
        )
        for index, record in enumerate(records)
        if record.get("task_id") is not None and record["task_id"] not in known_tasks
    ]
    if foreign:
        raise InvalidRequestError("batch references tasks of another study", foreign)

    handler = ingestion.handler_for(body["type"])
    with writer.transaction():
        handler(writer, session_id, records)
    return {"stored": len(records)}


def _open_session(sessions: SessionStore, session_id: int) -> SessionInfo:
    """Devuelve una sesión que exista y siga abierta.

    Raises:
        NotFoundError: Si la sesión no existe.
        ConflictError: Si la sesión está cerrada.
    """
    session = _existing_session(sessions, session_id)
    if session.ended_at is not None:
        raise ConflictError(f"session {session_id} is closed")
    return session


def _existing_session(sessions: SessionStore, session_id: int) -> SessionInfo:
    """Devuelve una sesión que exista, abierta o cerrada.

    Raises:
        NotFoundError: Si la sesión no existe.
    """
    session = sessions.get_session(session_id)
    if session is None:
        raise NotFoundError(f"session {session_id} not found")
    return session


def _check_contract_version(body: Any) -> None:
    """Rechaza con un mensaje claro un lote de otra versión mayor de los contratos.

    Si falta la versión o no tiene forma de versión, no hace nada: lo informa
    la validación del contrato.

    Raises:
        InvalidRequestError: Si la versión mayor no coincide con la del servidor.
    """
    version = body.get("contract_version") if isinstance(body, dict) else None
    if not isinstance(version, str):
        return
    current = contracts.contract_version()
    major, current_major = version.split(".", 1)[0], current.split(".", 1)[0]
    if major.isdigit() and major != current_major:
        message = (
            f"incompatible contract version {version}; "
            f"this server accepts {current_major}.x (current {current})"
        )
        raise InvalidRequestError(
            "incompatible contract version",
            [ErrorItem(record=None, field="contract_version", message=message)],
        )


def _validate(kind: str, body: Any, message: str) -> None:
    """Valida un cuerpo contra su contrato.

    En un lote, los errores de un registro llevan su posición en ``record`` y
    la ruta dentro del registro en ``field``.

    Args:
        kind: Tipo de documento en ``contracts/``.
        body: Cuerpo decodificado desde JSON.
        message: Resumen para la respuesta si hay errores.

    Raises:
        InvalidRequestError: Si el cuerpo no cumple el contrato.
    """
    errors = contracts.validate(kind, body)
    if errors:
        items = [_error_item(error.path, error.message) for error in errors]
        raise InvalidRequestError(message, items)


def _error_item(path: tuple[str | int, ...], message: str) -> ErrorItem:
    """Convierte la ruta de un error del contrato en registro y campo."""
    if len(path) >= 2 and path[0] == "records" and isinstance(path[1], int):
        return ErrorItem(record=path[1], field=_join(path[2:]), message=message)
    return ErrorItem(record=None, field=_join(path), message=message)


def _join(path: Sequence[str | int]) -> str:
    """Une una ruta con ``/``."""
    return "/".join(str(part) for part in path)
