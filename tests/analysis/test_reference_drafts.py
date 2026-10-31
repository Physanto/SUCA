"""Extracción de rutas y candidatas de referencia, con persistencia de borradores."""

import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from analysis import cleaning, columns, reference, screens
from analysis.loader import SESSION_FRAMES, SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import StageError, analyze_session, main
from scripts.simulation import scenarios
from shared import contracts, db


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Grabación con un intervalo de tarea conocido para los casos unitarios."""
    loaded = repository.load_session(1)
    start = loaded.session.started_at
    return replace(
        loaded,
        session=replace(loaded.session, mode="reference"),
        tasks=columns.frame(
            "tasks", [{"task_id": 1, "t_start": start, "t_end": start + 3000, "ended_by": "done"}]
        ),
    )


def capture(data: SessionData, records: list[dict[str, Any]]) -> SessionData:
    """Arma eventos relativos al inicio de la sesión con descriptores del simulador."""
    events = []
    for record in records:
        events.append(
            {
                "type": "click",
                "url": "https://shop.local/product/8812?q=one",
                "title": "Producto",
                "screen": "/product/{id}",
                "task_id": 1,
                "element": scenarios.ADD_TO_CART.descriptor(),
                **record,
                "t": data.session.started_at + record["t"],
            }
        )
    return replace(data, events=columns.frame("events", events))


def empty_results() -> dict[str, pd.DataFrame]:
    """Las cuatro tablas de resultados con sus columnas y sin filas."""
    return dict(
        zip(
            ("episodes", "incidents", "task_results", "usability_index"),
            (columns.empty(table) for table in columns.RESULT_TABLES),
            strict=True,
        )
    )


def validate_draft(row: Any) -> None:
    """Comprueba los JSON generados con el contrato real de referencia."""
    assert (
        contracts.validate(
            "reference",
            {
                "steps": row.steps,
                "candidates": row.candidates,
                "end_condition": None,
                "required_steps": [],
            },
        )
        == []
    )


def test_extracts_only_steps_in_stable_time_order_and_keeps_raw_screens(data: SessionData) -> None:
    loaded = capture(
        data,
        [
            {"t": 30, "type": "screen_change"},
            {"t": 10},
            {"t": 20, "type": "form_submit", "element": scenarios.SHIP_FORM.descriptor()},
            {"t": 20, "element": scenarios.CHECKOUT.descriptor()},
            {"t": 5, "element": scenarios.ZOOM_BADGE.descriptor()},
            {"t": 6, "element": None},
            {"t": 7, "type": "form_submit", "element": None},
            {"t": 8, "type": "field_change"},
            {"t": 9, "type": "dblclick"},
        ],
    )
    before = loaded.events.copy(deep=True)

    steps = reference.extract_steps(loaded.events)

    assert [step["type"] for step in steps] == ["click", "form_submit", "click", "screen_change"]
    assert [step["t"] - data.session.started_at for step in steps] == [10, 20, 20, 30]
    assert all(
        step["screen"] == {"url": "https://shop.local/product/8812?q=one", "title": "Producto"}
        for step in steps
    )
    assert steps[-1]["element"] is None
    assert steps[0]["element"] == scenarios.ADD_TO_CART.descriptor()
    assert_frame_equal(loaded.events, before, check_exact=True)
    assert (
        contracts.validate(
            "reference",
            {"steps": steps, "candidates": [], "end_condition": None, "required_steps": []},
        )
        == []
    )


def test_proposes_only_observed_text_and_roles_on_the_final_screen(
    data: SessionData, params: Parameters
) -> None:
    label = {
        **scenarios.ADD_TO_CART.descriptor(),
        "text": "  Pedido confirmado  ",
        "role": "status",
    }
    loaded = capture(
        data,
        [
            {"t": 0, "element": scenarios.CHECKOUT.descriptor()},
            {"t": 100, "type": "screen_change", "url": "https://shop.local/order/99/confirmation"},
            {"t": 200, "url": "https://shop.local/order/99/confirmation", "element": label},
            {"t": 300, "url": "https://shop.local/order/99/confirmation", "element": label},
            {"t": 400, "type": "camera_gap", "url": "https://shop.local/other"},
        ],
    )
    before = {name: getattr(loaded, name).copy(deep=True) for name in SESSION_FRAMES}

    found = reference.extract_drafts(loaded, params)

    columns.validate(found, "reference_draft")
    [draft] = list(found.itertuples())
    assert draft.task_id == 1 and draft.duration_ms == 3000
    assert draft.candidates == [
        {"type": "url_pattern", "pattern": "/order/{id}/confirmation"},
        {"type": "visible_text", "text": "Pedido confirmado"},
        {"type": "element_present", "text": "Pedido confirmado", "role": "status"},
    ]
    validate_draft(draft)
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(loaded, name), before[name], check_exact=True)


@pytest.mark.parametrize(
    ("url", "pattern"),
    [
        ("https://shop.local/product/123?from=search#details", "/product/{id}"),
        ("https://shop.local/#!/order/42?from=cart", "/order/{id}"),
        ("https://shop.local/app#/order/42?from=cart", "/app#/order/{id}"),
    ],
)
def test_url_candidates_share_screen_normalization_without_using_the_page_title(
    data: SessionData, params: Parameters, url: str, pattern: str
) -> None:
    loaded = capture(data, [{"t": 20, "type": "screen_change", "url": url, "title": "Título"}])
    found = reference.extract_drafts(loaded, params)
    assert found.iloc[0]["candidates"] == [{"type": "url_pattern", "pattern": pattern}]


def test_returning_to_the_same_url_does_not_reuse_elements_from_a_previous_visit(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0},
            {"t": 10, "type": "screen_change", "url": "https://shop.local/other"},
            {"t": 20, "type": "screen_change", "element": None},
        ],
    )
    assert reference.extract_drafts(loaded, params).iloc[0]["candidates"] == [
        {"type": "url_pattern", "pattern": "/product/{id}"}
    ]


def test_partitions_by_task_and_interval_and_ignores_unassigned_events(
    data: SessionData, params: Parameters
) -> None:
    start = data.session.started_at
    data = replace(
        data,
        tasks=columns.frame(
            "tasks",
            [
                {"task_id": 1, "t_start": start, "t_end": start + 100, "ended_by": "done"},
                {
                    "task_id": 2,
                    "t_start": start + 200,
                    "t_end": start + 300,
                    "ended_by": "reference",
                },
            ],
        ),
    )
    loaded = capture(
        data,
        [
            {"t": 0},
            {"t": 100},
            {"t": 101},
            {"t": 150, "task_id": None},
            {"t": 199, "task_id": 2},
            {"t": 200, "task_id": 2},
            {"t": 300, "task_id": 2},
            {"t": 301, "task_id": 2},
            {"t": 250, "task_id": 99},
        ],
    )
    found = reference.extract_drafts(loaded, params)
    assert found["task_id"].tolist() == [1, 2]
    assert found["duration_ms"].tolist() == [100, 100]
    assert [[step["t"] - start for step in steps] for steps in found["steps"]] == [
        [0, 100],
        [200, 300],
    ]


@pytest.mark.parametrize("case", ["free", "guided", "abandoned", "no_tasks", "no_steps", "invalid"])
def test_sessions_and_tasks_without_a_recorded_route_produce_no_drafts(
    data: SessionData, params: Parameters, case: str
) -> None:
    loaded = capture(data, [{"t": 20}])
    if case in ("free", "guided"):
        loaded = replace(loaded, session=replace(loaded.session, mode=case))
    elif case == "no_tasks":
        loaded = replace(loaded, tasks=columns.empty("tasks"))
    elif case == "no_steps":
        loaded = capture(data, [{"t": 20, "type": "mousemove", "element": None}])
    elif case == "abandoned":
        loaded.tasks.loc[0, "ended_by"] = "gave_up"
    else:
        loaded.tasks.loc[0, "t_end"] = loaded.tasks.iloc[0]["t_start"] - 1
    assert_frame_equal(reference.extract_drafts(loaded, params), columns.empty("reference_draft"))


@pytest.fixture
def recording_repository(connection: sqlite3.Connection) -> SqliteAnalysisRepository:
    """Convierte la sesión pequeña en una grabación, sin alterar sus datos capturados."""
    connection.execute("UPDATE session SET mode = 'reference' WHERE id = 1")
    return SqliteAnalysisRepository(connection)


def test_analysis_creates_and_updates_drafts_idempotently_without_confirming_them(
    recording_repository: SqliteAnalysisRepository,
    connection: sqlite3.Connection,
    params: Parameters,
) -> None:
    first = analyze_session(recording_repository, 1, params)
    row = dict(connection.execute("SELECT * FROM reference WHERE source_session_id = 1").fetchone())
    assert row["task_id"] == 1 and row["status"] == "draft"
    assert row["end_condition"] is None and json.loads(row["required_steps"]) == []
    assert json.loads(row["steps"]) == first.reference_drafts.iloc[0]["steps"]
    assert row["duration_ms"] == 29100
    connection.execute(
        "UPDATE reference SET steps = '[]', candidates = '[]' WHERE id = ?", (row["id"],)
    )

    second = analyze_session(recording_repository, 1, params)

    assert_frame_equal(first.reference_drafts, second.reference_drafts, check_exact=True)
    rows = [
        dict(item)
        for item in connection.execute("SELECT * FROM reference WHERE source_session_id = 1")
    ]
    assert rows == [row]
    assert first.task_results.empty and first.usability_index.empty


def test_reanalysis_preserves_a_reference_confirmed_by_the_evaluator(
    recording_repository: SqliteAnalysisRepository,
    connection: sqlite3.Connection,
    params: Parameters,
) -> None:
    analyze_session(recording_repository, 1, params)
    connection.execute(
        "UPDATE reference SET status = 'confirmed', end_condition = ?, required_steps = '[0]'"
        " WHERE source_session_id = 1",
        (json.dumps({"type": "visible_text", "text": "Elegida por el evaluador"}),),
    )
    before = [tuple(row) for row in connection.execute("SELECT * FROM reference ORDER BY id")]
    analyze_session(recording_repository, 1, params)
    assert [
        tuple(row) for row in connection.execute("SELECT * FROM reference ORDER BY id")
    ] == before


@pytest.mark.parametrize(
    "case",
    [
        "foreign_task",
        "unrecorded_task",
        "wrong_mode",
        "invalid_steps",
        "invalid_candidates",
        "invalid_duration",
    ],
)
def test_invalid_drafts_leave_existing_results_and_references_untouched(
    recording_repository: SqliteAnalysisRepository,
    connection: sqlite3.Connection,
    params: Parameters,
    case: str,
) -> None:
    analyze_session(recording_repository, 1, params)
    drafts = reference.extract_drafts(recording_repository.load_session(1), params)
    if case == "foreign_task":
        drafts.loc[0, "task_id"] = 3
    elif case == "unrecorded_task":
        drafts.loc[0, "task_id"] = 2
    elif case == "wrong_mode":
        connection.execute("UPDATE session SET mode = 'guided' WHERE id = 1")
    elif case == "invalid_steps":
        drafts.at[0, "steps"] = [{"type": "click"}]
    elif case == "invalid_candidates":
        drafts.at[0, "candidates"] = [{"type": "visible_text"}]
    else:
        drafts.loc[0, "duration_ms"] = float("inf")
    before = {
        table: list(connection.execute(f"SELECT * FROM {table}"))
        for table in (*columns.RESULT_TABLES, "reference")
    }
    with pytest.raises(ValueError):
        recording_repository.save_results(
            1, **empty_results(), params_version="test", reference_drafts=drafts
        )
    assert {table: list(connection.execute(f"SELECT * FROM {table}")) for table in before} == before


def test_result_insert_failure_rolls_back_draft_updates_in_the_same_transaction(
    recording_repository: SqliteAnalysisRepository,
    connection: sqlite3.Connection,
    params: Parameters,
) -> None:
    result = analyze_session(recording_repository, 1, params)
    before = {
        table: list(connection.execute(f"SELECT * FROM {table}"))
        for table in (*columns.RESULT_TABLES, "reference")
    }
    drafts = result.reference_drafts.copy(deep=True)
    drafts.at[0, "candidates"] = [{"type": "url_pattern", "pattern": "/changed"}]
    connection.execute(
        "CREATE TRIGGER fail_incident BEFORE INSERT ON incident BEGIN"
        " SELECT RAISE(ABORT, 'test result failure'); END"
    )
    results = empty_results()
    results["incidents"] = columns.frame("incident", [{"type": "dead_click", "t": 1}])
    with pytest.raises(sqlite3.IntegrityError, match="test result failure"):
        recording_repository.save_results(
            1, **results, params_version="test", reference_drafts=drafts
        )
    assert {table: list(connection.execute(f"SELECT * FROM {table}")) for table in before} == before


def test_failed_extraction_stops_the_pipeline_before_any_write(
    recording_repository: SqliteAnalysisRepository,
    connection: sqlite3.Connection,
    params: Parameters,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_session(recording_repository, 1, params)
    before = list(connection.execute("SELECT * FROM reference"))

    def broken(data: SessionData, params: Parameters) -> pd.DataFrame:
        raise ValueError("bad recording")

    monkeypatch.setattr(reference, "extract_drafts", broken)
    with pytest.raises(StageError, match="stage 'reference_drafts' failed: bad recording"):
        analyze_session(recording_repository, 1, params)
    assert list(connection.execute("SELECT * FROM reference")) == before


def test_mock_routes_match_recorded_steps_and_include_the_correct_url_candidate(
    mock: Any, params: Parameters, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    database = tmp_path / "reference.db"
    shutil.copyfile(mock.path, database)
    session_id = mock.session("reference")["session_id"]
    with closing(db.open_database(database)) as connection:
        expected_steps = {
            row["task_id"]: json.loads(row["steps"])
            for row in connection.execute(
                "SELECT * FROM reference WHERE source_session_id = ?", (session_id,)
            )
        }
        # Se retiran las referencias precargadas; el análisis debe reconstruirlas.
        connection.execute("DELETE FROM reference WHERE source_session_id = ?", (session_id,))
        connection.commit()
        loaded = SqliteAnalysisRepository(connection).load_session(session_id)
        found = reference.extract_drafts(
            screens.assign_screens(cleaning.clean(loaded, params), params), params
        )
        assert len(found) == 4
        for row in found.itertuples():
            assert row.steps == expected_steps[row.task_id]
            # Inicio, fin y duración se redondean por separado a décimas en el
            # simulador; la resta de timestamps añade menos de 0,001 ms binarios.
            assert row.duration_ms == pytest.approx(
                next(
                    item["duration_ms"]
                    for item in mock.truth["references"]
                    if item["task_id"] == row.task_id
                ),
                rel=0,
                abs=0.101,
            )
            validate_draft(row)
        correct = mock.truth["references"][0]
        assert (
            correct["end_condition"]
            in found.loc[found["task_id"] == correct["task_id"], "candidates"].iloc[0]
        )

    assert main(["--session", str(session_id), "--db", str(database)]) == 0
    assert "4 reference drafts" in capsys.readouterr().out
    with closing(db.open_database(database)) as connection:
        rows = list(connection.execute("SELECT * FROM reference ORDER BY task_id"))
        assert len(rows) == 4 and all(row["status"] == "draft" for row in rows)
        assert all(row["end_condition"] is None for row in rows)
        for row in rows:
            assert json.loads(row["steps"]) == expected_steps[row["task_id"]]
