"""Endpoint de capturas de la sesión: POST /sessions/{id}/frames."""

import base64
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from shared.config import Config

Example = Callable[[str], Any]


def test_saves_the_frame_in_the_folder_of_its_session(
    client: TestClient,
    config: Config,
    connection: sqlite3.Connection,
    session_id: int,
    example: Example,
) -> None:
    body = example("new-frame.valid.json")

    response = client.post(f"/sessions/{session_id}/frames", json=body)

    assert response.status_code == 201
    file_path = response.json()["file_path"]
    assert file_path.startswith(f"frames/{session_id}/") and file_path.endswith(".jpg")
    stored = config.database.path.parent / file_path
    assert stored.read_bytes() == base64.b64decode(body["image"].split(",", 1)[1])
    row = connection.execute("SELECT * FROM session_frame").fetchone()
    assert (row["id"], row["session_id"], row["t"], row["file_path"]) == (
        response.json()["frame_id"],
        session_id,
        body["t"],
        file_path,
    )


def test_a_frame_of_an_unknown_or_closed_session_is_not_saved(
    client: TestClient, session_id: int, example: Example, count: Callable[[str], int]
) -> None:
    body = example("new-frame.valid.json")

    unknown = client.post("/sessions/999/frames", json=body)
    client.post(f"/sessions/{session_id}/close")
    closed = client.post(f"/sessions/{session_id}/frames", json=body)

    assert (unknown.status_code, closed.status_code) == (404, 409)
    assert count("session_frame") == 0


def test_only_jpeg_frames_are_accepted(
    client: TestClient, session_id: int, example: Example, count: Callable[[str], int]
) -> None:
    body = example("new-frame.valid.json")
    body["image"] = body["image"].replace("/9j/", "AAAA", 1)

    response = client.post(f"/sessions/{session_id}/frames", json=body)

    assert response.status_code == 422
    assert response.json()["errors"][0]["message"] == "image content is not jpeg"
    assert count("session_frame") == 0


def test_deleting_the_session_deletes_its_frames(
    client: TestClient, connection: sqlite3.Connection, session_id: int, example: Example
) -> None:
    client.post(f"/sessions/{session_id}/frames", json=example("new-frame.valid.json"))

    connection.execute("DELETE FROM session WHERE id = ?", (session_id,))

    assert connection.execute("SELECT COUNT(*) FROM session_frame").fetchone()[0] == 0
