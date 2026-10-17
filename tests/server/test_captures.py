"""Endpoint de capturas de pantalla: POST /captures."""

import base64
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server import services
from server.repositories import SqliteRepository
from shared.config import Config

Example = Callable[[str], Any]


def test_saves_the_image_next_to_the_database(
    client: TestClient,
    config: Config,
    connection: sqlite3.Connection,
    example: Example,
    now: float,
) -> None:
    body = example("new-capture.valid.json")

    response = client.post("/captures", json=body)

    assert response.status_code == 201
    file_path = response.json()["file_path"]
    assert file_path.startswith("captures/1/") and file_path.endswith(".png")
    stored = config.database.path.parent / file_path
    assert stored.read_bytes() == base64.b64decode(body["image"].split(",", 1)[1])
    row = connection.execute("SELECT * FROM screen_capture").fetchone()
    assert (row["id"], row["study_id"], row["file_path"], row["t"]) == (
        response.json()["capture_id"],
        1,
        file_path,
        now,
    )


def test_file_names_are_generated_by_the_server(client: TestClient, example: Example) -> None:
    body = example("new-capture.valid.json")

    first = client.post("/captures", json=body).json()["file_path"]
    second = client.post("/captures", json=body).json()["file_path"]

    assert first != second


@pytest.mark.parametrize(
    ("image", "message"),
    [
        ("data:image/jpeg;base64,{png}", "image content is not jpeg"),
        ("data:image/png;base64,abc", "image is not valid base64"),
    ],
)
def test_invalid_images_are_rejected(
    client: TestClient, example: Example, config: Config, image: str, message: str
) -> None:
    body = example("new-capture.valid.json")
    png = body["image"].split(",", 1)[1]

    response = client.post("/captures", json={**body, "image": image.format(png=png)})

    assert response.status_code == 422
    assert response.json()["errors"] == [{"record": None, "field": "image", "message": message}]
    assert not (config.database.path.parent / "captures").exists()


def test_too_large_images_are_rejected(
    client: TestClient, example: Example, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "MAX_CAPTURE_BYTES", 10)

    response = client.post("/captures", json=example("new-capture.valid.json"))

    assert response.status_code == 422
    assert "larger than 10 bytes" in response.json()["errors"][0]["message"]


def test_unknown_study_is_reported_in_the_body_field(
    client: TestClient, example: Example
) -> None:
    response = client.post("/captures", json={**example("new-capture.valid.json"), "study_id": 9})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "study_id"


def test_capture_request_must_match_its_contract(client: TestClient, example: Example) -> None:
    response = client.post("/captures", json=example("new-capture.invalid.not-a-data-url.json"))

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "image"


def test_no_orphan_file_is_left_if_the_row_cannot_be_saved(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    repository = SqliteRepository(connection, data_dir=tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        repository.add_capture(
            study_id=999, screen={"url": "u", "title": ""}, image=b"x", extension="png", t=1.0
        )

    assert list((tmp_path / "captures").rglob("*")) == [tmp_path / "captures" / "999"]
