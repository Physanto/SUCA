"""Endpoints de sesiones: crear, cerrar y guardar el SUS."""

import json
import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import routes
from server.services import sus_score

Example = Callable[[str], Any]


def test_creates_a_session_and_its_participant(
    client: TestClient, connection: sqlite3.Connection, example: Example, now: float
) -> None:
    body = example("new-session.valid.json")

    response = client.post("/sessions", json=body)

    assert response.status_code == 201
    assert response.json() == {"session_id": 1, "started_at": now}
    row = connection.execute("SELECT * FROM session WHERE id = 1").fetchone()
    assert (row["study_id"], row["participant_id"], row["version"], row["mode"]) == (
        1,
        "P07",
        "V1",
        "guided",
    )
    assert row["started_at"] == now
    assert row["ended_at"] is None
    assert json.loads(row["screen_info"]) == body["screen_info"]
    assert connection.execute("SELECT id FROM participant").fetchall()[0]["id"] == "P07"


def test_a_participant_can_have_several_sessions(
    create_session: Callable[..., int], count: Callable[[str], int]
) -> None:
    create_session(mode="guided")
    create_session(mode="free")

    assert count("session") == 2
    assert count("participant") == 1


def test_unknown_study_is_reported_in_the_body_field(
    client: TestClient, example: Example
) -> None:
    response = client.post("/sessions", json={**example("new-session.valid.json"), "study_id": 9})

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"record": None, "field": "study_id", "message": "study 9 not found"}
    ]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"participant_id": "Ana Gómez"}, "participant_id"),
        ({"mode": "demo"}, "mode"),
        ({"screen_info": {"window_width": 1}}, "screen_info/chrome_version"),
    ],
)
def test_session_request_must_match_its_contract(
    client: TestClient, example: Example, changes: dict[str, Any], field: str
) -> None:
    response = client.post("/sessions", json={**example("new-session.valid.json"), **changes})

    assert response.status_code == 422
    assert field in [error["field"] for error in response.json()["errors"]]


def test_session_request_must_be_an_object(client: TestClient) -> None:
    response = client.post("/sessions", json=[1, 2])

    assert response.status_code == 422


def test_closes_a_session(
    client: TestClient, connection: sqlite3.Connection, session_id: int, now: float
) -> None:
    response = client.post(f"/sessions/{session_id}/close")

    assert response.status_code == 200
    assert response.json() == {"session_id": session_id, "ended_at": now}
    ended_at = connection.execute("SELECT ended_at FROM session").fetchone()[0]
    assert ended_at == now


def test_closing_twice_keeps_the_first_end(
    app: FastAPI, client: TestClient, session_id: int, now: float
) -> None:
    client.post(f"/sessions/{session_id}/close")
    app.dependency_overrides[routes.get_clock] = lambda: lambda: now + 5000

    response = client.post(f"/sessions/{session_id}/close")

    assert response.status_code == 200
    assert response.json()["ended_at"] == now


def test_closing_an_unknown_session_is_not_found(client: TestClient) -> None:
    assert client.post("/sessions/99/close").status_code == 404


def test_saves_sus_answers_with_their_score(
    client: TestClient, connection: sqlite3.Connection, session_id: int, example: Example
) -> None:
    body = example("sus-answers.valid.json")

    response = client.post(f"/sessions/{session_id}/sus", json=body)

    assert response.status_code == 200
    assert response.json() == {"score": 82.5}
    row = connection.execute("SELECT answers, score FROM sus_response").fetchone()
    assert (json.loads(row["answers"]), row["score"]) == (body["answers"], 82.5)


def test_sending_sus_again_replaces_it(
    client: TestClient, count: Callable[[str], int], session_id: int
) -> None:
    client.post(f"/sessions/{session_id}/sus", json={"answers": [3] * 10})
    response = client.post(f"/sessions/{session_id}/sus", json={"answers": [5, 1] * 5})

    assert response.json() == {"score": 100.0}
    assert count("sus_response") == 1


def test_sus_of_a_closed_session_is_a_conflict(client: TestClient, session_id: int) -> None:
    client.post(f"/sessions/{session_id}/close")

    response = client.post(f"/sessions/{session_id}/sus", json={"answers": [3] * 10})

    assert response.status_code == 409
    assert response.json() == {"detail": f"session {session_id} is closed"}


def test_sus_of_an_unknown_session_is_not_found(client: TestClient) -> None:
    assert client.post("/sessions/99/sus", json={"answers": [3] * 10}).status_code == 404


def test_sus_answers_must_match_their_contract(
    client: TestClient, session_id: int, example: Example
) -> None:
    response = client.post(
        f"/sessions/{session_id}/sus", json=example("sus-answers.invalid.nine-answers.json")
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "answers"


@pytest.mark.parametrize(
    ("answers", "score"),
    [
        ([3] * 10, 50.0),
        ([5, 1] * 5, 100.0),
        ([1, 5] * 5, 0.0),
        ([4, 2, 4, 1, 5, 2, 4, 2, 4, 1], 82.5),
    ],
)
def test_sus_score_uses_the_standard_formula(answers: list[int], score: float) -> None:
    assert sus_score(answers) == score
