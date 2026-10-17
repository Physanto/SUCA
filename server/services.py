"""Casos de uso del servidor: validan, aplican las reglas y usan los repositorios.

Cada función recibe solo las interfaces que necesita y no sabe de HTTP: informa
los problemas con las excepciones de este módulo, que ``app.py`` traduce a
códigos de estado. Son funciones y no clases porque no guardan estado.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from server import ingestion
from server.repositories import (
    BatchWriter,
    ReferenceStore,
    SessionInfo,
    SessionStore,
    StudyReader,
)
from shared import contracts, db

Clock = Callable[[], float]
"""Función que devuelve el momento actual en milisegundos desde 1970."""

REFERENCE_MODE = "reference"
"""Valor de ``session_mode`` de las sesiones que graban referencias."""

DRAFT_REFERENCE = "draft"
"""Valor de ``reference_status`` de una referencia recién guardada."""

CONFIRMED_REFERENCE = "confirmed"
"""Valor de ``reference_status`` de una referencia confirmada por el evaluador."""


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


def list_studies(*, studies: StudyReader) -> list[dict[str, Any]]:
    """Devuelve todos los estudios.

    Args:
        studies: Consulta de estudios.

    Returns:
        Estudios con ``id``, ``name``, ``system_under_test`` y ``description``.
    """
    return studies.list_studies()


def list_tasks(study_id: int, *, studies: StudyReader) -> list[dict[str, Any]]:
    """Devuelve las tareas de un estudio con sus referencias confirmadas.

    Args:
        study_id: Estudio de la ruta.
        studies: Consulta de estudios.

    Returns:
        Tareas en orden, cada una con ``references``: lista de ``{id,
        end_condition}`` de sus referencias confirmadas (vacía si no tiene).

    Raises:
        NotFoundError: Si el estudio no existe.
    """
    if not studies.study_exists(study_id):
        raise NotFoundError(f"study {study_id} not found")
    references: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for reference in studies.list_references(study_id, CONFIRMED_REFERENCE):
        references[reference["task_id"]].append(
            {"id": reference["id"], "end_condition": reference["end_condition"]}
        )
    return [
        {**task, "references": references.get(task["id"], [])}
        for task in studies.list_tasks(study_id)
    ]


def create_session(
    body: Any, *, studies: StudyReader, sessions: SessionStore, now: Clock
) -> dict[str, Any]:
    """Crea una sesión, y su participante si el código es nuevo.

    Args:
        body: Petición que cumple ``requests/new-session.schema.json``.
        studies: Consulta de estudios.
        sessions: Creación de sesiones.
        now: Reloj para ``started_at``.

    Returns:
        ``session_id`` y ``started_at``.

    Raises:
        InvalidRequestError: Si la petición no cumple el contrato o el estudio
            no existe.
    """
    _validate("new-session", body, "session request does not match its contract")
    if not studies.study_exists(body["study_id"]):
        raise InvalidRequestError(
            "unknown study",
            [ErrorItem(None, "study_id", f"study {body['study_id']} not found")],
        )
    started_at = now()
    session_id = sessions.create_session(
        study_id=body["study_id"],
        participant_id=body["participant_id"],
        version=body["version"],
        mode=body["mode"],
        started_at=started_at,
        screen_info=body["screen_info"],
    )
    return {"session_id": session_id, "started_at": started_at}


def close_session(session_id: int, *, sessions: SessionStore, now: Clock) -> dict[str, Any]:
    """Cierra una sesión. Cerrar una sesión ya cerrada no la cambia.

    Args:
        session_id: Sesión de la ruta.
        sessions: Consulta y cierre de sesiones.
        now: Reloj para ``ended_at``.

    Returns:
        ``session_id`` y ``ended_at``.

    Raises:
        NotFoundError: Si la sesión no existe.
    """
    session = _existing_session(sessions, session_id)
    if session.ended_at is not None:
        return {"session_id": session_id, "ended_at": session.ended_at}
    ended_at = now()
    sessions.close_session(session_id, ended_at)
    return {"session_id": session_id, "ended_at": ended_at}


def save_sus(session_id: int, body: Any, *, sessions: SessionStore) -> dict[str, float]:
    """Guarda las respuestas del SUS de una sesión abierta y calcula su puntaje.

    Volver a enviarlas reemplaza las anteriores.

    Args:
        session_id: Sesión de la ruta.
        body: Petición que cumple ``requests/sus-answers.schema.json``.
        sessions: Consulta de sesiones y guardado del SUS.

    Returns:
        ``score``, de 0 a 100.

    Raises:
        NotFoundError: Si la sesión no existe.
        ConflictError: Si la sesión está cerrada.
        InvalidRequestError: Si las respuestas no cumplen el contrato.
    """
    _open_session(sessions, session_id)
    _validate("sus-answers", body, "sus answers do not match their contract")
    score = sus_score(body["answers"])
    sessions.save_sus(session_id, body["answers"], score)
    return {"score": score}


def sus_score(answers: Sequence[int]) -> float:
    """Calcula el puntaje SUS con la fórmula estándar.

    Los ítems impares (redactados en positivo) aportan ``respuesta - 1``; los
    pares (en negativo), ``5 - respuesta``. La suma se multiplica por 2,5.

    Args:
        answers: Las 10 respuestas, de 1 a 5, en orden.

    Returns:
        Puntaje de 0 a 100.
    """
    total = sum(
        answer - 1 if position % 2 == 0 else 5 - answer
        for position, answer in enumerate(answers)
    )
    return total * 2.5


def create_reference(
    body: Any,
    *,
    sessions: SessionStore,
    studies: StudyReader,
    references: ReferenceStore,
) -> dict[str, int]:
    """Guarda en borrador la referencia grabada en una sesión de modo reference.

    La referencia nace sin pasos ni condiciones candidatas: las agrega el
    análisis. Guardar dos veces la misma tarea de la misma sesión devuelve la
    misma referencia.

    Args:
        body: Petición que cumple ``requests/new-reference.schema.json``.
        sessions: Consulta de sesiones.
        studies: Consulta de tareas del estudio.
        references: Creación de referencias.

    Returns:
        ``reference_id``.

    Raises:
        InvalidRequestError: Si la petición no cumple el contrato, la sesión no
            existe o no es de modo reference, o la tarea es de otro estudio.
    """
    _validate("new-reference", body, "reference request does not match its contract")
    session_id, task_id = body["source_session_id"], body["task_id"]
    session = sessions.get_session(session_id)
    if session is None:
        raise InvalidRequestError(
            "unknown session",
            [ErrorItem(None, "source_session_id", f"session {session_id} not found")],
        )
    if session.mode != REFERENCE_MODE:
        message = f"session {session_id} has mode {session.mode!r}, expected {REFERENCE_MODE!r}"
        raise InvalidRequestError(
            "session is not a reference recording",
            [ErrorItem(None, "source_session_id", message)],
        )
    if task_id not in studies.task_ids(session.study_id):
        message = f"task {task_id} does not belong to study {session.study_id}"
        raise InvalidRequestError("task of another study", [ErrorItem(None, "task_id", message)])
    reference_id = references.create_draft_reference(
        task_id=task_id, source_session_id=session_id, status=DRAFT_REFERENCE
    )
    return {"reference_id": reference_id}


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
