"""Cada ejemplo válido de ``contracts/examples`` se acepta y queda guardado.

Los ejemplos de lote se envían a POST /sessions/{id}/batches (los de un solo
registro, envueltos en un lote de su tipo) y los de cuerpos de petición, a su
endpoint. Los demás no son cuerpos de petición y se cubren en otro lado.
"""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.services import REFERENCE_MODE
from shared.config import ROOT_DIR

Example = Callable[[str], Any]

BATCH_RECORD_TABLES = {
    "events": "event",
    "gaze": "gaze_sample",
    "face": "face_sample",
    "tasks": "session_task",
    "calibration": "calibration",
}
"""Tabla donde termina cada tipo de registro de lote."""

REQUEST_EXAMPLES = {
    "new-session.valid.json": "session",
    "sus-answers.valid.json": "sus_response",
    "new-reference.valid.json": "reference",
    "new-capture.valid.json": "screen_capture",
    "new-frame.valid.json": "session_frame",
}
"""Ejemplo de cuerpo de petición y tabla donde queda guardado."""

NOT_REQUEST_BODIES = {
    "element.valid.json": "viaja dentro de los eventos",
    "reference.valid.json": "lo produce el análisis, no la API",
    "study.valid.json": "se carga con scripts.load_study",
}
"""Ejemplos válidos que no se envían a la API, y por qué."""


def test_every_valid_example_is_covered() -> None:
    names = {path.name for path in (ROOT_DIR / "contracts" / "examples").glob("*.valid.json")}
    covered = (
        {"batch.valid.json"}
        | {f"{kind}.valid.json" for kind in BATCH_RECORD_TABLES}
        | set(REQUEST_EXAMPLES)
        | set(NOT_REQUEST_BODIES)
    )

    assert names == covered


def test_example_batch_is_stored(
    client: TestClient, session_id: int, example: Example, count: Callable[[str], int]
) -> None:
    response = client.post(f"/sessions/{session_id}/batches", json=example("batch.valid.json"))

    assert response.status_code == 200
    assert count("event") == len(example("batch.valid.json")["records"])


@pytest.mark.parametrize("batch_type", sorted(BATCH_RECORD_TABLES))
def test_example_record_is_stored(
    client: TestClient,
    session_id: int,
    example: Example,
    make_batch: Callable[[str, list[dict[str, Any]]], dict[str, Any]],
    count: Callable[[str], int],
    batch_type: str,
) -> None:
    record = example(f"{batch_type}.valid.json")

    response = client.post(f"/sessions/{session_id}/batches", json=make_batch(batch_type, [record]))

    assert response.status_code == 200, response.json()
    assert count(BATCH_RECORD_TABLES[batch_type]) == 1


@pytest.mark.parametrize("name", sorted(REQUEST_EXAMPLES))
def test_example_request_is_stored(
    client: TestClient,
    create_session: Callable[..., int],
    example: Example,
    count: Callable[[str], int],
    name: str,
) -> None:
    # Los ejemplos que nombran una sesión usan la 1: se crea como la piden.
    if name == "new-reference.valid.json":
        create_session(mode=REFERENCE_MODE)
    elif name in ("sus-answers.valid.json", "new-frame.valid.json"):
        create_session()
    path = {
        "new-session.valid.json": "/sessions",
        "sus-answers.valid.json": "/sessions/1/sus",
        "new-reference.valid.json": "/references",
        "new-capture.valid.json": "/captures",
        "new-frame.valid.json": "/sessions/1/frames",
    }[name]

    response = client.post(path, json=example(name))

    assert response.status_code in (200, 201), response.json()
    assert count(REQUEST_EXAMPLES[name]) == 1
