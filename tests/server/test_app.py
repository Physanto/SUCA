"""Arranque del servidor, comprobación del token y formato de los errores."""

import dataclasses
import json
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import __main__ as server_main
from server.app import create_app
from server.security import TOKEN_HEADER
from shared import contracts, db
from shared.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH, Config, DatabaseConfig

ROUTES = [
    ("GET", "/health"),
    ("GET", "/studies"),
    ("GET", "/studies/1/tasks"),
    ("POST", "/sessions"),
    ("POST", "/sessions/1/batches"),
    ("POST", "/sessions/1/sus"),
    ("POST", "/sessions/1/close"),
    ("POST", "/references"),
    ("POST", "/captures"),
]


def test_app_fails_fast_without_database(config: Config, tmp_path: Path) -> None:
    missing = dataclasses.replace(
        config, database=DatabaseConfig(path=tmp_path / "missing.db", mock_path=tmp_path / "m.db")
    )

    with pytest.raises(FileNotFoundError):
        create_app(missing)


def test_app_fails_fast_with_another_schema_version(config: Config) -> None:
    with closing(db.connect(config.database.path)) as connection:
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")

    with pytest.raises(db.SchemaVersionError):
        create_app(config)


def test_health_reports_versions(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "contract_version": contracts.contract_version(),
        "schema_version": db.expected_schema_version(),
    }


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_requires_the_token(app: FastAPI, method: str, path: str) -> None:
    anonymous = TestClient(app)

    response = anonymous.request(method, path, json={})

    assert response.status_code == 401
    assert TOKEN_HEADER in response.json()["detail"]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_a_wrong_token_is_rejected(app: FastAPI, method: str, path: str) -> None:
    intruder = TestClient(app, headers={TOKEN_HEADER: "not-the-token"})

    assert intruder.request(method, path, json={}).status_code == 401


def test_malformed_json_is_reported_with_the_common_error_format(
    client: TestClient, session_id: int
) -> None:
    response = client.post(
        f"/sessions/{session_id}/batches",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"record": None, "field": "", "message": "JSON decode error"}
    ]


def test_path_parameters_are_validated(client: TestClient) -> None:
    response = client.get("/studies/abc/tasks")

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "study_id"


def test_cors_is_not_enabled(client: TestClient) -> None:
    """Sin CORS, una página web no puede enviar el encabezado del token."""
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": TOKEN_HEADER,
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_main_serves_on_the_configured_loopback_address(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data: dict[str, Any] = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data["database"]["path"] = str(config.database.path)
    config_path = tmp_path / "shared.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config_path))
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server_main.uvicorn, "run", lambda app, **options: calls.append(options))

    assert server_main.main() == 0
    assert calls == [{"host": "127.0.0.1", "port": data["server"]["port"]}]


def test_main_reports_a_missing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data: dict[str, Any] = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data["database"]["path"] = str(tmp_path / "missing.db")
    config_path = tmp_path / "shared.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config_path))

    assert server_main.main() == 1
    assert "scripts.init_db" in capsys.readouterr().err
