"""Fixtures de las pruebas del servidor: una base nueva con el estudio de ejemplo por prueba.

Con ``--import-mode=importlib`` las pruebas no pueden importar funciones de este
archivo, así que los ayudantes son fixtures que devuelven funciones.
"""

import dataclasses
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.init_db import init_db
from scripts.load_study import load_study, read_study
from server import routes
from server.app import create_app
from server.security import TOKEN_HEADER
from shared import contracts, db
from shared.config import DEFAULT_CONFIG_PATH, ROOT_DIR, Config, DatabaseConfig, load_config

EXAMPLES = ROOT_DIR / "contracts" / "examples"
EXAMPLE_STUDY = ROOT_DIR / "studies" / "example.yaml"
NOW = 1_791_380_200_000.0


@pytest.fixture
def now() -> float:
    """Momento fijo que devuelve el reloj del servidor en las pruebas."""
    return NOW


@pytest.fixture
def example() -> Callable[[str], Any]:
    """Función que lee un ejemplo de ``contracts/examples`` por su nombre."""

    def read(name: str) -> Any:
        return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))

    return read


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Configuración con una base temporal que ya tiene el estudio de ejemplo (id 1, tareas 1–4)."""
    database = tmp_path / "data" / "suca.db"
    init_db(database)
    with closing(db.open_database(database)) as connection:
        load_study(connection, read_study(EXAMPLE_STUDY))
    base = load_config(DEFAULT_CONFIG_PATH)
    return dataclasses.replace(
        base, database=DatabaseConfig(path=database, mock_path=tmp_path / "data" / "mock.db")
    )


@pytest.fixture
def app(config: Config) -> FastAPI:
    """App del servidor con el reloj fijo en ``NOW``."""
    app = create_app(config)
    app.dependency_overrides[routes.get_clock] = lambda: lambda: NOW
    return app


@pytest.fixture
def client(app: FastAPI, config: Config) -> TestClient:
    """Cliente que envía el token correcto en cada petición."""
    return TestClient(app, headers={TOKEN_HEADER: config.server.token})


@pytest.fixture
def connection(config: Config) -> Iterator[sqlite3.Connection]:
    """Conexión a la base de la prueba, para revisar lo guardado."""
    connection = db.open_database(config.database.path)
    yield connection
    connection.close()


@pytest.fixture
def create_session(
    client: TestClient, example: Callable[[str], Any]
) -> Callable[..., int]:
    """Función que crea una sesión a partir del ejemplo del contrato y devuelve su id."""

    def create(**changes: Any) -> int:
        response = client.post("/sessions", json={**example("new-session.valid.json"), **changes})
        assert response.status_code == 201, response.json()
        return response.json()["session_id"]

    return create


@pytest.fixture
def session_id(create_session: Callable[..., int]) -> int:
    """Sesión guiada abierta."""
    return create_session()


@pytest.fixture
def make_batch() -> Callable[[str, list[dict[str, Any]]], dict[str, Any]]:
    """Función que arma un lote con la versión actual de los contratos."""

    def make(batch_type: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "contract_version": contracts.contract_version(),
            "type": batch_type,
            "records": records,
        }

    return make


@pytest.fixture
def count(connection: sqlite3.Connection) -> Callable[[str], int]:
    """Función que cuenta las filas de una tabla."""

    def rows(table: str) -> int:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    return rows
