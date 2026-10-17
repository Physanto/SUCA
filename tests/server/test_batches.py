"""Endpoint de lotes: POST /sessions/{id}/batches y los manejadores por tipo."""

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import ingestion, services
from server.repositories import BatchWriter
from server.security import TOKEN_HEADER
from shared import contracts
from shared.config import Config

Example = Callable[[str], Any]
MakeBatch = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
Count = Callable[[str], int]


def test_stores_every_event_of_the_example_batch(
    client: TestClient, session_id: int, example: Example, count: Count
) -> None:
    response = client.post(f"/sessions/{session_id}/batches", json=example("batch.valid.json"))

    assert response.status_code == 200
    assert response.json() == {"stored": 14}
    assert count("event") == 14


def test_event_columns_keep_the_record(
    client: TestClient,
    connection: sqlite3.Connection,
    session_id: int,
    example: Example,
    make_batch: MakeBatch,
) -> None:
    record = example("events.valid.json")

    client.post(f"/sessions/{session_id}/batches", json=make_batch("events", [record]))

    row = connection.execute("SELECT * FROM event").fetchone()
    assert (row["session_id"], row["t"], row["type"], row["x"], row["y"]) == (
        session_id,
        record["t"],
        "click",
        record["x"],
        record["y"],
    )
    assert json.loads(row["screen"]) == record["screen"]
    assert json.loads(row["element"]) == record["element"]
    assert row["task_id"] == record["task_id"]


def test_face_values_and_flags_are_stored(
    client: TestClient,
    connection: sqlite3.Connection,
    session_id: int,
    example: Example,
    make_batch: MakeBatch,
) -> None:
    record = example("face.valid.json")

    client.post(f"/sessions/{session_id}/batches", json=make_batch("face", [record]))

    row = connection.execute('SELECT "values", face_detected FROM face_sample').fetchone()
    assert json.loads(row["values"]) == record["values"]
    assert row["face_detected"] == 1


def test_calibration_summarizes_the_last_error_of_each_type(
    client: TestClient,
    connection: sqlite3.Connection,
    session_id: int,
    example: Example,
    make_batch: MakeBatch,
) -> None:
    first = example("calibration.valid.json")
    recalibration = {**first, "t": first["t"] + 60_000, "error_deg": 1.9}
    final = {**first, "t": first["t"] + 900_000, "type": "final", "error_deg": 3.4}

    client.post(
        f"/sessions/{session_id}/batches",
        json=make_batch("calibration", [first, recalibration, final]),
    )

    row = connection.execute(
        "SELECT calibration_error_start, calibration_error_end FROM session"
    ).fetchone()
    assert tuple(row) == (1.9, 3.4)
    assert connection.execute("SELECT COUNT(*) FROM calibration").fetchone()[0] == 3


def test_sending_a_task_again_replaces_it(
    client: TestClient,
    connection: sqlite3.Connection,
    session_id: int,
    example: Example,
    make_batch: MakeBatch,
) -> None:
    record = example("tasks.valid.json")
    retried = {**record, "t_end": record["t_end"] + 1000}

    client.post(f"/sessions/{session_id}/batches", json=make_batch("tasks", [record]))
    response = client.post(f"/sessions/{session_id}/batches", json=make_batch("tasks", [retried]))

    assert response.status_code == 200
    rows = connection.execute("SELECT t_end FROM session_task").fetchall()
    assert [row["t_end"] for row in rows] == [retried["t_end"]]


def test_unknown_session_is_not_found(client: TestClient, example: Example) -> None:
    response = client.post("/sessions/99/batches", json=example("batch.valid.json"))

    assert response.status_code == 404
    assert response.json() == {"detail": "session 99 not found"}


def test_closed_session_is_a_conflict(
    client: TestClient, session_id: int, example: Example, count: Count
) -> None:
    client.post(f"/sessions/{session_id}/close")

    response = client.post(f"/sessions/{session_id}/batches", json=example("batch.valid.json"))

    assert response.status_code == 409
    assert count("event") == 0


def test_contract_errors_name_the_record_and_field(
    client: TestClient, session_id: int, example: Example, count: Count
) -> None:
    batch = example("batch.valid.json")
    del batch["records"][3]["x"]
    batch["records"][10]["element"]["text"] = "x" * 51

    response = client.post(f"/sessions/{session_id}/batches", json=batch)

    assert response.status_code == 422
    assert response.json()["detail"] == "batch does not match its contract"
    assert [(error["record"], error["field"]) for error in response.json()["errors"]] == [
        (3, "x"),
        (10, "element/text"),
    ]
    assert count("event") == 0


def test_envelope_errors_have_no_record(
    client: TestClient, session_id: int, example: Example
) -> None:
    response = client.post(
        f"/sessions/{session_id}/batches", json=example("batch.invalid.unknown-type.json")
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["record"] is None
    assert response.json()["errors"][0]["field"] == "type"


def test_incompatible_contract_version_is_explained(
    client: TestClient, session_id: int, example: Example
) -> None:
    response = client.post(
        f"/sessions/{session_id}/batches",
        json=example("batch.invalid.incompatible-contract-version.json"),
    )

    assert response.status_code == 422
    [error] = response.json()["errors"]
    assert error["field"] == "contract_version"
    assert error["message"] == (
        "incompatible contract version 2.0.0; this server accepts 1.x "
        f"(current {contracts.contract_version()})"
    )


def test_tasks_of_another_study_are_rejected(
    client: TestClient, session_id: int, example: Example, count: Count
) -> None:
    batch = example("batch.valid.json")
    batch["records"][5]["task_id"] = 99

    response = client.post(f"/sessions/{session_id}/batches", json=batch)

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"record": 5, "field": "task_id", "message": "task 99 does not belong to study 1"}
    ]
    assert count("event") == 0


def test_a_batch_is_stored_completely_or_not_at_all(
    app: FastAPI,
    config: Config,
    session_id: int,
    example: Example,
    count: Count,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el manejador falla después de escribir, no queda nada guardado."""
    original = ingestion.HANDLERS["events"]

    def store_then_fail(
        writer: BatchWriter, session: int, records: Sequence[Mapping[str, Any]]
    ) -> None:
        original(writer, session, records)
        raise RuntimeError("disk full")

    monkeypatch.setitem(ingestion.HANDLERS, "events", store_then_fail)
    client = TestClient(
        app, headers={TOKEN_HEADER: config.server.token}, raise_server_exceptions=False
    )

    response = client.post(f"/sessions/{session_id}/batches", json=example("batch.valid.json"))

    assert response.status_code == 500
    assert count("event") == 0


def test_every_batch_type_has_a_handler() -> None:
    assert set(ingestion.HANDLERS) == set(contracts.enums()["batch_type"])


def test_handlers_cannot_be_registered_twice() -> None:
    with pytest.raises(RuntimeError, match="duplicate handler"):
        ingestion.register("events")(ingestion.store_events)


def test_enum_values_used_by_the_server_exist_in_the_contracts() -> None:
    enums = contracts.enums()

    assert set(ingestion.CALIBRATION_ERROR_COLUMNS) == set(enums["calibration_type"])
    assert services.REFERENCE_MODE in enums["session_mode"]
    assert {services.DRAFT_REFERENCE, services.CONFIRMED_REFERENCE} == set(
        enums["reference_status"]
    )

