"""Cálculo del índice con resultados por tarea y persistencia junto al análisis de fricción."""

import json
import shutil
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from analysis import columns, detectors, reference, usability_index
from analysis.loader import SESSION_FRAMES, SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import analyze_session
from scripts.generate_mock_data import ground_truth_path
from shared import db


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Tres tareas, dos completadas y referencias de duraciones y rutas distintas."""
    loaded = repository.load_session(1)
    return replace(
        loaded,
        tasks=columns.frame(
            "tasks",
            [
                {"task_id": 1, "t_start": 0, "t_end": 60_000, "ended_by": "reference"},
                {"task_id": 2, "t_start": 70_000, "t_end": 100_000, "ended_by": "reference"},
                {"task_id": 3, "t_start": 110_000, "t_end": 140_000, "ended_by": "gave_up"},
            ],
        ),
        references=columns.frame(
            "references",
            [
                {
                    "id": 1,
                    "task_id": 1,
                    "steps": [{}, {}],
                    "required_steps": [],
                    "duration_ms": 15_000,
                },
                {
                    "id": 2,
                    "task_id": 2,
                    "steps": [{}, {}, {}],
                    "required_steps": [],
                    "duration_ms": 60_000,
                },
            ],
        ),
    )


@pytest.fixture
def task_results() -> pd.DataFrame:
    """Resultados con una tarea más rápida que la referencia y otra abandonada."""
    return columns.frame(
        "task_result",
        [
            {"task_id": 1, "success": True, "duration_ms": 60_000, "steps": 4},
            {"task_id": 2, "success": True, "duration_ms": 30_000, "steps": 2},
            {"task_id": 3, "success": False, "duration_ms": 30_000, "steps": 1},
        ],
    )


@pytest.fixture
def incidents() -> pd.DataFrame:
    """Cuatro incidentes de tarea y dos ajenos al tiempo de las tareas evaluadas."""
    return columns.frame(
        "incident",
        [
            {"type": "dead_click", "t": 1000.0, "task_id": task_id}
            for task_id in (1, 1, 2, 3, None, 99)
        ],
    )


def test_index_matches_a_hand_calculation_and_preserves_inputs(
    data: SessionData, task_results: pd.DataFrame, incidents: pd.DataFrame, params: Parameters
) -> None:
    before = {name: getattr(data, name).copy(deep=True) for name in SESSION_FRAMES}
    results_before, incidents_before = task_results.copy(deep=True), incidents.copy(deep=True)

    found = usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    )

    columns.validate(found, "usability_index")
    # E = 2/3; T = (1/4 + 1)/2; P = (2/4 + 1)/2.
    # Cuatro incidentes en dos minutos: F = 1 - (2/4).
    assert found.iloc[0].to_dict() == pytest.approx(
        {
            "effectiveness": 200 / 3,
            "time_efficiency": 62.5,
            "path_efficiency": 75,
            "friction": 50,
            "bui": 1525 / 24,
        }
    )
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(data, name), before[name], check_exact=True)
    assert_frame_equal(task_results, results_before, check_exact=True)
    assert_frame_equal(incidents, incidents_before, check_exact=True)


@pytest.mark.parametrize("mode", ["free", "reference"])
def test_only_guided_sessions_have_an_index(
    data: SessionData,
    task_results: pd.DataFrame,
    incidents: pd.DataFrame,
    params: Parameters,
    mode: str,
) -> None:
    data = replace(data, session=replace(data.session, mode=mode))
    assert_frame_equal(
        usability_index.compute(data, task_results, incidents, replace(params, friction_i_max=4)),
        columns.empty("usability_index"),
    )


@pytest.mark.parametrize("limit", [None, 0, -1, float("nan"), float("inf")])
def test_an_unset_or_invalid_threshold_does_not_use_a_mock_fallback(
    data: SessionData,
    task_results: pd.DataFrame,
    incidents: pd.DataFrame,
    params: Parameters,
    limit: float | None,
) -> None:
    assert usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=limit)
    ).empty


@pytest.mark.parametrize("case", ["empty", "partial", "foreign", "no_tasks", "no_reference"])
def test_incomplete_inputs_do_not_produce_a_partial_index(
    data: SessionData,
    task_results: pd.DataFrame,
    incidents: pd.DataFrame,
    params: Parameters,
    case: str,
) -> None:
    if case == "empty":
        task_results = columns.empty("task_result")
    elif case == "partial":
        task_results = task_results.iloc[:2]
    elif case == "foreign":
        task_results.loc[2, "task_id"] = 99
    elif case == "no_tasks":
        data = replace(data, tasks=columns.empty("tasks"))
    else:
        data = replace(data, references=columns.empty("references"))
    assert usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    ).empty


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("duration_ms", 0),
        ("duration_ms", -1),
        ("duration_ms", float("inf")),
        ("steps", 0),
        ("steps", -1),
    ],
)
def test_invalid_completed_task_measurements_do_not_produce_an_index(
    data: SessionData,
    task_results: pd.DataFrame,
    incidents: pd.DataFrame,
    params: Parameters,
    column: str,
    value: float,
) -> None:
    task_results.loc[0, column] = value
    assert usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    ).empty


@pytest.mark.parametrize("duration", [None, 0, -1, float("inf")])
def test_invalid_reference_durations_cannot_supply_an_efficiency(
    data: SessionData,
    task_results: pd.DataFrame,
    incidents: pd.DataFrame,
    params: Parameters,
    duration: float | None,
) -> None:
    data.references.loc[0, "duration_ms"] = duration
    assert usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    ).empty


def test_empty_reference_paths_cannot_supply_an_efficiency(
    data: SessionData, task_results: pd.DataFrame, incidents: pd.DataFrame, params: Parameters
) -> None:
    data.references.at[0, "steps"] = []
    assert usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    ).empty


def test_alternative_references_are_independent_of_row_order(
    data: SessionData, task_results: pd.DataFrame, incidents: pd.DataFrame, params: Parameters
) -> None:
    extra = data.references.iloc[[0]].copy(deep=True)
    extra.loc[extra.index[0], "id"] = 3
    extra.loc[extra.index[0], "duration_ms"] = 60_000
    extra.at[extra.index[0], "steps"] = [{}, {}, {}, {}]
    data = replace(data, references=pd.concat([data.references, extra], ignore_index=True))
    configured = replace(params, friction_i_max=4)
    found = usability_index.compute(data, task_results, incidents, configured)
    assert found.iloc[0]["time_efficiency"] == 100
    assert found.iloc[0]["path_efficiency"] == 100
    assert_frame_equal(
        found,
        usability_index.compute(
            replace(data, references=data.references.iloc[::-1]),
            task_results,
            incidents,
            configured,
        ),
    )


@pytest.mark.parametrize(("incident_count", "friction"), [(0, 100), (8, 0), (12, 0)])
def test_no_completed_tasks_have_zero_efficiencies_and_bounded_friction(
    data: SessionData,
    task_results: pd.DataFrame,
    params: Parameters,
    incident_count: int,
    friction: float,
) -> None:
    task_results["success"] = False
    task_results["steps"] = 0
    data = replace(data, references=columns.empty("references"))
    incidents = columns.frame(
        "incident", [{"type": "dead_click", "t": 1, "task_id": 1}] * incident_count
    )
    found = usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    )
    assert found.iloc[0].to_dict() == {
        "effectiveness": 0,
        "time_efficiency": 0,
        "path_efficiency": 0,
        "friction": friction,
        "bui": friction / 4,
    }
    task_results["duration_ms"] = 0
    assert usability_index.compute(
        data, task_results, incidents, replace(params, friction_i_max=4)
    ).empty


@pytest.mark.parametrize("key", ["reference", "guided_v0", "guided_v1", "guided_v2", "free_v1"])
def test_mock_index_from_known_task_results_and_incidents(
    mock: Any, params: Parameters, tmp_path: Path, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth = json.loads(ground_truth_path(mock.path).read_text(encoding="utf-8"))
    expected = next(item for item in truth["sessions"] if item["key"] == key)
    task_results = columns.frame(
        "task_result",
        [
            {name: item[name] for name in columns.spec("task_result").columns}
            for item in expected["tasks"]
        ],
    )
    # Aísla las fórmulas del índice inyectando resultados por tarea conocidos.
    monkeypatch.setattr(reference, "compare", lambda data, params: task_results.copy(deep=True))
    incidents = columns.frame(
        "incident",
        [
            {
                "type": item["type"],
                "t": item["t_start"],
                "screen": item["screen"],
                "task_id": item["task_id"],
                "element": item["element"],
            }
            for item in expected["incidents"]
        ],
    )
    monkeypatch.setattr(detectors, "detect", lambda data, params: incidents.copy(deep=True))
    configured = replace(params, version="mock", friction_i_max=truth["friction_i_max"])
    database = tmp_path / "index.db"
    shutil.copyfile(mock.path, database)
    with closing(db.open_database(database)) as connection:
        for table in columns.RESULT_TABLES:
            connection.execute(f"DELETE FROM {table}")
        connection.commit()
        repository = SqliteAnalysisRepository(connection)
        for _ in range(2):
            result = analyze_session(repository, expected["session_id"], configured)
            index = expected["usability_index"]
            columns.validate(result.usability_index, "usability_index")
            saved = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usability_index WHERE session_id = ?", (expected["session_id"],)
                )
            ]
            if index is None:
                assert result.usability_index.empty
                assert saved == []
            else:
                assert result.usability_index.iloc[0].to_dict() == pytest.approx(index, abs=0.005)
                assert len(saved) == 1
                assert saved[0].pop("session_id") == expected["session_id"]
                assert saved[0].pop("params_version") == "mock"
                assert saved[0] == result.usability_index.iloc[0].to_dict()
