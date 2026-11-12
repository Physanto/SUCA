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

DRIFT_CHECK = "drift_check"
"""Valor de ``calibration_type`` de una comprobación de deriva durante la sesión."""

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
                "state": record.get("state"),
                "confidence": record.get("confidence"),
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
    writer.insert_distinct(
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
                "css_px_per_cm": record.get("css_px_per_cm"),
                "camera_delay_ms": record.get("camera_delay_ms"),
                "precision_deg": record.get("precision_deg"),
                "return_error_deg": record.get("return_error_deg"),
                "estimator": record.get("estimator"),
                "corrected": _optional_flag(record.get("corrected")),
                "correction_x_px": record.get("correction_x_px"),
                "correction_y_px": record.get("correction_y_px"),
            }
            for record in records
        ],
    )
    # Las comprobaciones de deriva no resumen la sesión: solo el inicio y el final.
    latest = {
        CALIBRATION_ERROR_COLUMNS[record["type"]]: record["error_deg"]
        for record in records
        if record["type"] in CALIBRATION_ERROR_COLUMNS
    }
    if latest:
        writer.update_session(session_id, latest)


@register("layout")
def store_layout(
    writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]
) -> None:
    """Guarda la disposición de cada pantalla en ``page_layout``."""
    writer.insert(
        "page_layout",
        [
            {
                "session_id": session_id,
                "t": record["t"],
                "screen": to_json(record["screen"]),
                "viewport_width": record["viewport_width"],
                "viewport_height": record["viewport_height"],
                "scroll_x": record["scroll_x"],
                "scroll_y": record["scroll_y"],
                "regions": to_json(record["regions"]),
                "elements": to_json(record["elements"]),
                "truncated": int(record["truncated"]),
            }
            for record in records
        ],
    )


GAZE_FEATURE_COLUMNS = (
    "t",
    "face_detected",
    "head_yaw",
    "head_pitch",
    "head_roll",
    "head_tx",
    "head_ty",
    "head_tz",
    "distance_cm",
    "eye_u",
    "eye_v",
    "aspect",
    "left_h",
    "left_v",
    "left_open",
    "left_refined",
    "right_h",
    "right_v",
    "right_open",
    "right_refined",
    "blink",
    "state",
    "confidence",
    "raw_x",
    "raw_y",
    "viewport_width",
    "viewport_height",
    "scroll_x",
    "scroll_y",
)
"""Campos de ``gaze_features`` que se guardan, cada uno en su columna de ``gaze_feature``."""

_FLAG_COLUMNS = {"face_detected", "left_refined", "right_refined"}


@register("gaze_features")
def store_gaze_features(
    writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]
) -> None:
    """Guarda las características de mirada de cada cuadro en ``gaze_feature``."""
    writer.insert(
        "gaze_feature",
        [
            {"session_id": session_id}
            | {
                column: _optional_flag(record[column])
                if column in _FLAG_COLUMNS
                else record[column]
                for column in GAZE_FEATURE_COLUMNS
            }
            for record in records
        ],
    )


@register("gaze_target")
def store_gaze_targets(
    writer: BatchWriter, session_id: int, records: Sequence[Mapping[str, Any]]
) -> None:
    """Guarda los puntos que se pidió mirar en ``gaze_target``."""
    writer.insert(
        "gaze_target",
        [
            {
                "session_id": session_id,
                "t": record["t_start"],
                "t_end": record["t_end"],
                "calibration_type": record["calibration_type"],
                "phase": record["phase"],
                "group": record["group"],
                "viewport_width": record["viewport_width"],
                "viewport_height": record["viewport_height"],
                "points": to_json(record["points"]),
            }
            for record in records
        ],
    )


def _optional_flag(value: bool | None) -> int | None:
    """Pasa un booleano opcional a 0/1; si falta, la columna queda en ``NULL``."""
    return None if value is None else int(value)


def _optional_json(value: Any) -> str | None:
    """Serializa un valor opcional; si falta, la columna queda en ``NULL``."""
    return None if value is None else to_json(value)
