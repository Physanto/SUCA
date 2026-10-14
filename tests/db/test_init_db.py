"""Pruebas de la creación de la base con ``scripts.init_db``."""

import json
from contextlib import closing
from pathlib import Path

import pytest

from scripts.init_db import init_db, main
from shared import db
from shared.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH


def count_participants(path: Path) -> int:
    """Cuenta los participantes de una base."""
    with closing(db.open_database(path)) as connection:
        return connection.execute("SELECT COUNT(*) FROM participant").fetchone()[0]


def add_participant(path: Path) -> None:
    """Agrega un participante para comprobar si los datos sobreviven."""
    with closing(db.open_database(path)) as connection:
        connection.execute("INSERT INTO participant (id) VALUES ('P01')")


def test_creates_database_and_missing_folders(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "data" / "suca.db"

    assert init_db(path) == "created"
    assert count_participants(path) == 0


def test_is_idempotent_and_keeps_data(database: Path) -> None:
    add_participant(database)

    assert init_db(database) == "unchanged"
    assert count_participants(database) == 1


def test_fails_on_another_schema_version(database: Path) -> None:
    with closing(db.connect(database)) as connection:
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")

    with pytest.raises(db.SchemaVersionError, match="--reset"):
        init_db(database)


def test_reset_recreates_an_empty_database(database: Path) -> None:
    add_participant(database)

    assert init_db(database, reset=True) == "recreated"
    assert count_participants(database) == 0


def test_reset_also_repairs_another_schema_version(database: Path) -> None:
    with closing(db.connect(database)) as connection:
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")

    assert init_db(database, reset=True) == "recreated"
    with closing(db.open_database(database)) as connection:
        assert db.schema_version(connection) == db.expected_schema_version()


def test_cli_uses_the_given_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "cli.db"

    assert main(["--db", str(path)]) == 0
    assert f"created: {path}" in capsys.readouterr().out


def test_cli_reset_asks_and_can_be_cancelled(
    database: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_participant(database)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    assert main(["--db", str(database), "--reset"]) == 1
    assert "Cancelado" in capsys.readouterr().out
    assert count_participants(database) == 1


def test_cli_reset_runs_after_confirmation(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_participant(database)
    monkeypatch.setattr("builtins.input", lambda prompt: "s")

    assert main(["--db", str(database), "--reset"]) == 0
    assert count_participants(database) == 0


def test_cli_reset_with_yes_does_not_ask(database: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(prompt: str) -> str:
        raise AssertionError("must not ask")

    monkeypatch.setattr("builtins.input", fail)

    assert main(["--db", str(database), "--reset", "--yes"]) == 0


def test_cli_reports_version_mismatch(
    database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with closing(db.connect(database)) as connection:
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")

    assert main(["--db", str(database)]) == 1
    assert "schema version is '0'" in capsys.readouterr().err


def test_cli_defaults_to_configured_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = tmp_path / "configured.db"
    data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data["database"]["path"] = str(configured)
    config_path = tmp_path / "shared.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config_path))

    assert main([]) == 0
    assert configured.exists()
