"""Pruebas de la carga de estudios con ``scripts.load_study``."""

import copy
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.load_study import StudyFileError, load_study, main, read_study
from shared.config import ROOT_DIR

EXAMPLE = ROOT_DIR / "studies" / "example.yaml"


@pytest.fixture
def example() -> dict[str, Any]:
    """Estudio de ejemplo ya validado."""
    return read_study(EXAMPLE)


def tasks_of(connection: sqlite3.Connection, study_id: int) -> list[tuple[int, int, str]]:
    """Tareas de un estudio: (id, posición, instrucción)."""
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT id, position, instruction FROM task WHERE study_id = ? ORDER BY position",
            (study_id,),
        )
    ]


def test_example_study_loads_with_four_tasks(
    connection: sqlite3.Connection, example: dict[str, Any]
) -> None:
    loaded = load_study(connection, example)

    study = connection.execute("SELECT * FROM study WHERE id = ?", (loaded.study_id,)).fetchone()
    assert study["name"] == example["name"]
    assert [position for _, position, _ in tasks_of(connection, loaded.study_id)] == [1, 2, 3, 4]
    assert len(loaded.task_ids) == 4


def test_yaml_text_with_hash_is_kept_whole(example: dict[str, Any]) -> None:
    """Un " #" sin comillas cortaría la instrucción como si fuera un comentario."""
    assert example["tasks"][3]["instruction"].endswith("Calle 10 # 20-30, Bogotá.")


def test_loading_twice_keeps_ids(connection: sqlite3.Connection, example: dict[str, Any]) -> None:
    first = load_study(connection, example)
    second = load_study(connection, example)

    assert second == first
    assert connection.execute("SELECT COUNT(*) FROM study").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM task").fetchone()[0] == 4


def test_reloading_updates_study_and_tasks_in_place(
    connection: sqlite3.Connection, example: dict[str, Any]
) -> None:
    first = load_study(connection, example)
    changed = copy.deepcopy(example)
    changed["description"] = "Otra descripción"
    changed["tasks"][0]["instruction"] = "Nueva instrucción"
    changed["tasks"].append({"instruction": "Quinta tarea"})

    second = load_study(connection, changed)

    assert second.task_ids[:4] == first.task_ids
    assert tasks_of(connection, first.study_id)[0][2] == "Nueva instrucción"
    assert len(second.task_ids) == 5
    description = connection.execute("SELECT description FROM study").fetchone()[0]
    assert description == "Otra descripción"


def test_tasks_without_data_are_removed(
    connection: sqlite3.Connection, example: dict[str, Any]
) -> None:
    load_study(connection, example)
    shorter = copy.deepcopy(example)
    shorter["tasks"] = shorter["tasks"][:2]

    loaded = load_study(connection, shorter)

    assert len(loaded.task_ids) == 2


def test_tasks_with_data_are_not_removed_and_nothing_changes(
    connection: sqlite3.Connection, example: dict[str, Any]
) -> None:
    loaded = load_study(connection, example)
    connection.execute("INSERT INTO participant (id) VALUES ('P01')")
    connection.execute(
        "INSERT INTO session (id, study_id, participant_id, version, mode, started_at) "
        "VALUES (1, ?, 'P01', 'V0', 'guided', 1)",
        (loaded.study_id,),
    )
    connection.execute(
        "INSERT INTO session_task (session_id, task_id, t_start, t_end, ended_by) "
        "VALUES (1, ?, 1, 2, 'done')",
        (loaded.task_ids[3],),
    )
    shorter = copy.deepcopy(example)
    shorter["tasks"] = shorter["tasks"][:3]
    shorter["tasks"][0]["instruction"] = "Cambio que no debe aplicarse"

    with pytest.raises(StudyFileError, match="recorded data"):
        load_study(connection, shorter)

    assert tasks_of(connection, loaded.study_id)[0][2] == example["tasks"][0]["instruction"]
    assert len(tasks_of(connection, loaded.study_id)) == 4


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("name: [sin cerrar\n", encoding="utf-8")

    with pytest.raises(StudyFileError, match="invalid YAML"):
        read_study(path)


def test_contract_errors_are_listed_by_field(tmp_path: Path) -> None:
    path = tmp_path / "study.yaml"
    path.write_text("name: X\nsystem_under_test: Y\ntasks:\n  - text: Z\n", encoding="utf-8")

    expected = r"tasks/0/instruction: 'instruction' is a required property"
    with pytest.raises(StudyFileError, match=expected):
        read_study(path)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(StudyFileError, match="cannot read file"):
        read_study(tmp_path / "missing.yaml")


def test_cli_loads_the_example(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(EXAMPLE), "--db", str(database)]) == 0
    assert "with 4 tasks" in capsys.readouterr().out


def test_cli_requires_an_initialized_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(EXAMPLE), "--db", str(tmp_path / "missing.db")]) == 1
    assert "scripts.init_db" in capsys.readouterr().err
