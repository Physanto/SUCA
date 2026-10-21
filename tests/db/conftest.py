"""Fixtures de las pruebas de base de datos: una base nueva por prueba."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.init_db import init_db
from shared import db


@pytest.fixture
def database(tmp_path: Path) -> Path:
    """Ruta de una base recién creada con el esquema completo."""
    path = tmp_path / "data" / "test.db"
    init_db(path)
    return path


@pytest.fixture
def connection(database: Path) -> Iterator[sqlite3.Connection]:
    """Conexión abierta a la base de la prueba."""
    connection = db.open_database(database)
    yield connection
    connection.close()


@pytest.fixture
def session_id(connection: sqlite3.Connection) -> int:
    """Crea un estudio, un participante y una sesión, y devuelve el id de la sesión."""
    with db.transaction(connection):
        connection.execute(
            "INSERT INTO study (id, name, system_under_test) VALUES (1, 'Study', 'App')"
        )
        connection.execute(
            "INSERT INTO task (id, study_id, position, instruction) VALUES (1, 1, 1, 'Do')"
        )
        connection.execute("INSERT INTO participant (id) VALUES ('P01')")
        connection.execute(
            "INSERT INTO session (id, study_id, participant_id, version, mode, started_at) "
            "VALUES (7, 1, 'P01', 'V0', 'guided', 1791380123456.2)"
        )
    return 7
