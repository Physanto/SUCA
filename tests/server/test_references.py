"""Endpoint de referencias: POST /references crea el borrador de una grabación."""

import copy
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from typing import Any

from fastapi.testclient import TestClient

from scripts.load_study import load_study, read_study
from shared import contracts, db
from shared.config import ROOT_DIR, Config


def test_creates_an_empty_draft_that_matches_the_reference_contract(
    client: TestClient, connection: sqlite3.Connection, create_session: Callable[..., int]
) -> None:
    session = create_session(mode="reference")

    response = client.post("/references", json={"task_id": 3, "source_session_id": session})

    assert response.status_code == 201
    assert response.json() == {"reference_id": 1}
    row = connection.execute("SELECT * FROM reference").fetchone()
    assert (row["task_id"], row["source_session_id"], row["status"]) == (3, session, "draft")
    document = {
        "steps": json.loads(row["steps"]),
        "candidates": json.loads(row["candidates"]),
        "end_condition": None,
        "required_steps": json.loads(row["required_steps"]),
    }
    assert contracts.validate("reference", document) == []


def test_saving_the_same_recording_twice_returns_the_same_reference(
    client: TestClient, create_session: Callable[..., int], count: Callable[[str], int]
) -> None:
    session = create_session(mode="reference")
    body = {"task_id": 3, "source_session_id": session}

    first = client.post("/references", json=body).json()
    second = client.post("/references", json=body).json()

    assert first == second
    assert count("reference") == 1


def test_only_reference_sessions_can_save_references(
    client: TestClient, session_id: int
) -> None:
    response = client.post("/references", json={"task_id": 3, "source_session_id": session_id})

    assert response.status_code == 422
    [error] = response.json()["errors"]
    assert error["field"] == "source_session_id"
    assert "expected 'reference'" in error["message"]


def test_unknown_source_session_is_reported_in_the_body_field(client: TestClient) -> None:
    response = client.post("/references", json={"task_id": 3, "source_session_id": 99})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "source_session_id"


def test_task_must_belong_to_the_study_of_the_session(
    client: TestClient, config: Config, create_session: Callable[..., int]
) -> None:
    other = copy.deepcopy(read_study(ROOT_DIR / "studies" / "example.yaml"))
    other["name"] = "Otro estudio"
    with closing(db.open_database(config.database.path)) as connection:
        foreign_task = load_study(connection, other).task_ids[0]
    session = create_session(mode="reference")

    response = client.post(
        "/references", json={"task_id": foreign_task, "source_session_id": session}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "task_id"


def test_reference_request_must_match_its_contract(client: TestClient) -> None:
    response = client.post("/references", json={"task_id": 3})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "source_session_id"


def test_confirmed_reference_reaches_the_task_list(
    client: TestClient, connection: sqlite3.Connection, create_session: Callable[..., int]
) -> None:
    """El ciclo completo: guardar en borrador, confirmar y ofrecerla al modo guiado."""
    session = create_session(mode="reference")
    reference_id = client.post(
        "/references", json={"task_id": 3, "source_session_id": session}
    ).json()["reference_id"]
    end_condition: dict[str, Any] = {"type": "visible_text", "text": "Pedido confirmado"}
    connection.execute(
        "UPDATE reference SET status = 'confirmed', end_condition = ? WHERE id = ?",
        (json.dumps(end_condition), reference_id),
    )

    tasks = client.get("/studies/1/tasks").json()

    assert tasks[2]["references"] == [{"id": reference_id, "end_condition": end_condition}]
