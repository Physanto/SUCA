"""Manejadores de lotes por tipo (Strategy + Registry).

Cada tipo de lote tiene una función que convierte sus registros, ya validados
contra el contrato, en filas de su tabla. La función se registra con
``@register(<tipo>)``. Agregar un tipo de lote solo requiere su manejador (y su
tabla en el esquema): el servicio que recibe los lotes no cambia. Una prueba
exige que cada valor de ``batch_type`` tenga su manejador.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from server.repositories import BatchWriter, to_json

BatchHandler = Callable[[BatchWriter, int, Sequence[Mapping[str, Any]]], None]
"""Firma de un manejador: escritor, id de la sesión y registros del lote."""

HANDLERS: dict[str, BatchHandler] = {}
"""Manejadores registrados, por tipo de lote."""

INITIAL_CALIBRATION = "initial"
"""Valor de ``calibration_type`` de la calibración del inicio."""

FINAL_CALIBRATION = "final"
"""Valor de ``calibration_type`` de la validación del final."""

CALIBRATION_ERROR_COLUMNS = {
    INITIAL_CALIBRATION: "calibration_error_start",
    FINAL_CALIBRATION: "calibration_error_end",
}
"""Columna de ``session`` que resume el error de cada tipo de calibración."""


def register(batch_type: str) -> Callable[[BatchHandler], BatchHandler]:
    """Registra un manejador para un tipo de lote.

    Args:
        batch_type: Valor de ``batch_type`` que atiende el manejador.

    Returns:
        Decorador que registra la función y la devuelve sin cambios.

    Raises:
        RuntimeError: Si ya hay un manejador para ese tipo.
    """

    def decorator(handler: BatchHandler) -> BatchHandler:
        if batch_type in HANDLERS:
            raise RuntimeError(f"duplicate handler for batch type {batch_type!r}")
        HANDLERS[batch_type] = handler
        return handler

    return decorator


def handler_for(batch_type: str) -> BatchHandler:
    """Devuelve el manejador de un tipo de lote.

    Args:
        batch_type: Tipo del lote, ya validado contra el contrato.

    Returns:
        Manejador registrado.

    Raises:
        LookupError: Si nadie registró un manejador para ese tipo.
    """
    try:
        return HANDLERS[batch_type]
    except KeyError:
        raise LookupError(f"no handler registered for batch type {batch_type!r}") from None


@register("events")
def store_events(
    writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]
) -> None:
    """Guarda eventos de interacción en ``event``."""
    writer.insert(
        "event",
        [
            {
                "session_id": session_id,
                "t": record["t"],
                "type": record["type"],
                "x": record.get("x"),
                "y": record.get("y"),
                "screen": to_json(record["screen"]),
                "task_id": record["task_id"],
                "element": _optional_json(record.get("element")),
                "data": _optional_json(record.get("data")),
            }
            for record in records
        ],
    )


@register("gaze")
def store_gaze(writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]) -> None:
    """Guarda muestras de mirada en ``gaze_sample``."""
    writer.insert(
        "gaze_sample",
        [
            {
                "session_id": session_id,
                "t": record["t"],
                "x": record.get("x"),
                "y": record.get("y"),
                "scroll_x": record.get("scroll_x"),
                "scroll_y": record.get("scroll_y"),
                "element_selector": record.get("element_selector"),
                "zone": record.get("zone"),
                "valid": int(record["valid"]),
            }
            for record in records
        ],
    )


@register("face")
def store_face(writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]) -> None:
    """Guarda muestras faciales en ``face_sample``."""
    writer.insert(
        "face_sample",
        [
            {
                "session_id": session_id,
                "t": record["t"],
                "values": _optional_json(record.get("values")),
                "head_yaw": record.get("head_yaw"),
                "head_pitch": record.get("head_pitch"),
                "face_detected": int(record["face_detected"]),
            }
            for record in records
        ],
    )


@register("tasks")
def store_tasks(writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]) -> None:
    """Guarda el inicio y el fin de cada tarea en ``session_task``.

    Reenviar el registro de una tarea (por un reintento) lo reemplaza en lugar
    de fallar.
    """
    writer.upsert(
        "session_task",
        [
            {
                "session_id": session_id,
                "task_id": record["task_id"],
                "t_start": record["t_start"],
                "t_end": record["t_end"],
                "ended_by": record["ended_by"],
            }
            for record in records
        ],
        key=("session_id", "task_id"),
    )


@register("calibration")
def store_calibration(
    writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]
) -> None:
    """Guarda calibraciones en ``calibration`` y resume su error en ``session``.

    La sesión guarda el error en grados de la última calibración de cada tipo:
    si hubo que recalibrar, cuenta la última.
    """
    writer.insert(
        "calibration",
        [
            {
                "session_id": session_id,
                "t": record["t"],
                "type": record["type"],
                "error_px": record["error_px"],
                "error_deg": record["error_deg"],
                "accepted": int(record["accepted"]),
                "viewing_distance_cm": record.get("viewing_distance_cm"),
                "camera_delay_ms": record.get("camera_delay_ms"),
            }
            for record in records
        ],
    )
    latest = {CALIBRATION_ERROR_COLUMNS[record["type"]]: record["error_deg"] for record in records}
    writer.update_session(session_id, latest)


def _optional_json(value: Any) -> str | None:
    """Serializa un valor opcional; si falta, la columna queda en ``NULL``."""
    return None if value is None else to_json(value)
