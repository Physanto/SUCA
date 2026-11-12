"""Pruebas de la fábrica de conexiones y las transacciones de ``shared.db``."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from shared import db


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="scripts.init_db"):
        db.connect(path)

    assert not path.exists()


def test_connection_uses_wal_foreign_keys_and_named_rows(
    connection: sqlite3.Connection,
) -> None:
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_S * 1000
    assert connection.execute("SELECT 1 AS one").fetchone()["one"] == 1


def test_transaction_commits_on_success(connection: sqlite3.Connection) -> None:
    with db.transaction(connection):
        connection.execute("INSERT INTO participant (id) VALUES ('P01')")
        connection.execute("INSERT INTO participant (id) VALUES ('P02')")

    assert connection.execute("SELECT COUNT(*) FROM participant").fetchone()[0] == 2


def test_transaction_rolls_back_everything_on_error(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError), db.transaction(connection):
        connection.execute("INSERT INTO participant (id) VALUES ('P01')")
        connection.execute("INSERT INTO participant (id) VALUES ('P01')")

    assert connection.execute("SELECT COUNT(*) FROM participant").fetchone()[0] == 0
    assert not connection.in_transaction


def test_nested_transactions_are_rejected(connection: sqlite3.Connection) -> None:
    with db.transaction(connection), pytest.raises(RuntimeError, match="nested"):
        with db.transaction(connection):
            pass


def test_open_database_rejects_other_schema_versions(database: Path) -> None:
    with closing(db.connect(database)) as connection:
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")

    with pytest.raises(db.SchemaVersionError, match="'0', expected '8'"):
        db.open_database(database)


def test_open_database_rejects_databases_of_other_systems(tmp_path: Path) -> None:
    path = tmp_path / "other.db"
    with closing(db.connect(path, create=True)) as connection:
        connection.execute("CREATE TABLE something (id INTEGER)")

    with pytest.raises(db.SchemaVersionError, match="None"):
        db.open_database(path)
