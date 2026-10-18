"""Pruebas del repositorio del análisis sobre SQLite."""

import json
import sqlite3
from collections.abc import Callable

import pandas as pd
import pytest

from analysis import columns
from analysis.columns import ColumnValidationError
from analysis.loader import (
    CONFIRMED_REFERENCE,
    NotFoundError,
    SqliteAnalysisRepository,
    validate_session_data,
)
from shared import contracts

T0 = 1_791_380_000_000.0


def results(incidents: int = 1) -> dict[str, pd.DataFrame]:
    """Resultados de prueba con una cantidad dada de incidentes."""
    incident = {"type": "dead_click", "t": T0 + 1000, "screen": "/cart/{id}", "task_id": 1}
    return {
        "episodes": columns.frame(
            "episode",
            [{"type": "screen", "t_start": T0, "t_end": T0 + 2000, "metrics": {"returns": 0}}],
        ),
        "incidents": columns.frame(
            "incident", [{**incident, "element": {"tag": "button"}}] * incidents
        ),
        "task_results": columns.frame(
            "task_result", [{"task_id": 1, "success": True, "duration_ms": 29100, "steps": 4}]
        ),
        "usability_index": columns.frame(
            "usability_index",
            [
                {
                    "effectiveness": 100.0,
                    "time_efficiency": 85.9,
                    "path_efficiency": 75.0,
                    "friction": 90.0,
                    "bui": 87.7,
                }
            ],
        ),
    }


def test_confirmed_reference_is_a_contract_status() -> None:
    assert CONFIRMED_REFERENCE in contracts.enums()["reference_status"]


def test_loads_the_session_and_its_data(repository: SqliteAnalysisRepository) -> None:
    data = repository.load_session(1)

    validate_session_data(data)
    assert data.session.mode == "guided"
    assert data.session.closed
    assert data.session.screen_info == {"window_width": 1280, "window_height": 800}
    assert list(data.events["type"]) == ["mousemove", "click", "screen_change"]
    click = data.events.iloc[1]
    assert (click["url"], click["title"]) == ("https://shop.local/cart/8812", "Carrito")
    assert click["screen"] == click["url"]
    assert click["element"]["id"] == "pay"
    assert pd.isna(data.events.iloc[0]["task_id"])
    assert data.events.iloc[2]["data"] == {}
    assert list(data.gaze["valid"]) == [True, False]
    assert data.face.iloc[0]["values"] == {"smile": 0.2}
    assert list(data.calibrations["type"]) == ["initial"]
    assert list(data.tasks["ended_by"]) == ["reference"]


def test_loads_only_the_confirmed_references_of_the_study(
    repository: SqliteAnalysisRepository,
) -> None:
    references = repository.load_session(1).references

    assert list(references["id"]) == [1]
    assert references.iloc[0]["end_condition"]["text"] == "Pedido confirmado"
    assert references.iloc[0]["required_steps"] == [0]


def test_loads_an_open_session(repository: SqliteAnalysisRepository) -> None:
    data = repository.load_session(2)

    assert not data.session.closed
    assert len(data.events) == 1
    assert len(data.tasks) == 0


def test_lists_the_sessions_of_a_study(repository: SqliteAnalysisRepository) -> None:
    sessions = repository.list_sessions(1)

    assert [(session.id, session.closed) for session in sessions] == [(1, True), (2, False)]
    assert repository.list_sessions(2) == []


def test_unknown_sessions_and_studies_are_not_found(repository: SqliteAnalysisRepository) -> None:
    with pytest.raises(NotFoundError, match="session 99 not found"):
        repository.load_session(99)
    with pytest.raises(NotFoundError, match="study 99 not found"):
        repository.list_sessions(99)


def test_saves_results_with_session_and_parameters_version(
    repository: SqliteAnalysisRepository, connection: sqlite3.Connection
) -> None:
    repository.save_results(1, **results(), params_version="pilot-1")

    incident = dict(connection.execute("SELECT * FROM incident").fetchone())
    assert incident["session_id"] == 1
    assert json.loads(incident["element"]) == {"tag": "button"}
    episode = dict(connection.execute("SELECT * FROM episode").fetchone())
    assert json.loads(episode["metrics"]) == {"returns": 0}
    assert episode["outcome"] is None
    task = dict(connection.execute("SELECT * FROM task_result").fetchone())
    assert (task["success"], task["deviation_step"], task["off_path_ms"]) == (1, None, None)
    index = dict(connection.execute("SELECT * FROM usability_index").fetchone())
    assert (index["bui"], index["params_version"]) == (87.7, "pilot-1")


def test_saving_twice_replaces_instead_of_duplicating(
    repository: SqliteAnalysisRepository, count_rows: Callable[[str], int]
) -> None:
    repository.save_results(1, **results(incidents=3), params_version="pilot-1")
    repository.save_results(1, **results(incidents=2), params_version="pilot-2")

    assert count_rows("incident") == 2
    assert count_rows("episode") == count_rows("task_result") == count_rows("usability_index") == 1


def test_saving_empty_results_removes_the_previous_ones(
    repository: SqliteAnalysisRepository, count_rows: Callable[[str], int]
) -> None:
    repository.save_results(1, **results(), params_version="pilot-1")
    empty = {
        "episodes": columns.empty("episode"),
        "incidents": columns.empty("incident"),
        "task_results": columns.empty("task_result"),
        "usability_index": columns.empty("usability_index"),
    }

    repository.save_results(1, **empty, params_version="pilot-1")

    assert [count_rows(table) for table in columns.RESULT_TABLES] == [0, 0, 0, 0]


def test_invalid_results_leave_the_previous_ones_untouched(
    repository: SqliteAnalysisRepository, count_rows: Callable[[str], int]
) -> None:
    repository.save_results(1, **results(incidents=2), params_version="pilot-1")
    broken = results() | {"task_results": pd.DataFrame({"task_id": [1]})}

    with pytest.raises(ColumnValidationError, match="task_result: missing columns"):
        repository.save_results(1, **broken, params_version="pilot-1")

    assert count_rows("incident") == 2


def test_saving_one_session_keeps_the_results_of_the_others(
    repository: SqliteAnalysisRepository, connection: sqlite3.Connection
) -> None:
    repository.save_results(1, **results(incidents=2), params_version="pilot-1")
    repository.save_results(2, **results(incidents=1), params_version="pilot-1")
    repository.save_results(2, **results(incidents=1), params_version="pilot-1")

    counts = dict(
        connection.execute("SELECT session_id, COUNT(*) FROM incident GROUP BY session_id")
    )
    assert counts == {1: 2, 2: 1}
