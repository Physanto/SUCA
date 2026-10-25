"""Pruebas de ráfagas de clics, respuestas, plazos y señales de foco."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import cleaning, columns, detectors, screens
from analysis.loader import SESSION_FRAMES, SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import analyze_session
from scripts.simulation import scenarios, store
from scripts.simulation.builder import SessionBuilder
from shared import db


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Datos base para eventos con límites controlados."""
    return repository.load_session(1)


def capture(data: SessionData, records: list[dict]) -> SessionData:
    """Construye eventos con tiempos relativos y una pantalla normalizada."""
    t0 = data.session.started_at
    rows = []
    for item in records:
        values = item.get("data")
        if isinstance(values, dict) and "click_t" in values:
            values = {**values, "click_t": t0 + values["click_t"]}
        rows.append(
            {
                "type": "click",
                "x": 50,
                "y": 30,
                "url": "https://shop.local/",
                "title": "Inicio",
                "screen": "/",
                "element": scenarios.ADD_TO_CART.descriptor(),
                **item,
                "t": t0 + item["t"],
                "data": values,
            }
        )
    return replace(data, events=columns.frame("events", rows))


@pytest.mark.parametrize("kind", ["rage_click", "dead_click"])
def test_builder_patterns_match_their_incident_truth(
    connection: sqlite3.Connection, params: Parameters, kind: str
) -> None:
    builder = SessionBuilder(study_id=1, camera=False).on_screen(scenarios.PRODUCT)
    if kind == "rage_click":
        builder.with_rage_click(scenarios.ADD_TO_CART)
    else:
        builder.with_dead_click(scenarios.ZOOM_BADGE)
    recording = builder.build()
    loaded = screens.assign_screens(
        cleaning.clean(store.load_session(connection, recording), params), params
    )

    found = detectors.DETECTORS.get(kind).find(loaded, params)

    truth = columns.frame(
        "incident",
        [
            {
                "type": item.type,
                "t": item.t_start,
                "screen": item.screen,
                "task_id": item.task_id,
                "element": item.element,
            }
            for item in recording.truth.incidents
            if item.type == kind
        ],
    )
    assert_frame_equal(found, truth, check_exact=True)


@pytest.mark.parametrize(
    ("times", "positions", "expected"),
    [
        ([0, 500, 1000], [0, 30, 30], [0]),
        ([0, 500, 1001], [0, 0, 0], []),
        ([0, 100, 200], [0, 30, 31], []),
        ([0, 100], [0, 0], []),
        ([0, 100, 200, 300], [0, 30, 60, 60], [100]),
        ([0, 800, 1001, 1100], [0, 0, 0, 0], [800]),
        ([0, 100, 200, 300, 400, 500], [0] * 6, [0]),
        ([0, 100, 200, 1300, 1400, 1500], [0] * 6, [0, 1300]),
    ],
)
def test_rage_click_time_radius_sliding_windows_and_nonoverlapping_bursts(
    data: SessionData,
    params: Parameters,
    times: list[int],
    positions: list[int],
    expected: list[int],
) -> None:
    loaded = capture(
        data, [{"t": t, "x": x, "y": 0} for t, x in zip(times, positions, strict=True)]
    )

    found = detectors.RageClickDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at + t for t in expected]


@pytest.mark.parametrize("boundary", ["screen", "task", "reload", "url"])
def test_rage_click_does_not_join_different_contexts(
    data: SessionData, params: Parameters, boundary: str
) -> None:
    records = [{"t": 0}, {"t": 100}, {"t": 200}]
    if boundary == "screen":
        records[-1]["screen"] = "/other"
    elif boundary == "task":
        records[-1]["task_id"] = 1
    elif boundary == "url":
        records[-1]["url"] = "https://shop.local/?page=other"
    else:
        records.insert(2, {"t": 150, "type": "screen_change"})

    found = detectors.RageClickDetector().find(capture(data, records), params)

    assert found.empty


def test_rage_click_uses_parameters_and_ignores_duplicate_browser_event_types(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, [{"t": 0}, {"t": 100}, {"t": 101, "type": "dblclick"}])

    assert detectors.RageClickDetector().find(loaded, params).empty
    custom = replace(params, rage_click=replace(params.rage_click, min_clicks=2))
    assert len(detectors.RageClickDetector().find(loaded, custom)) == 1


@pytest.mark.parametrize(
    ("window_ms", "radius_px", "count"), [(100, 10, 1), (100, 5, 0), (50, 10, 0)]
)
def test_rage_click_uses_the_configured_time_window_and_radius(
    data: SessionData, params: Parameters, window_ms: int, radius_px: int, count: int
) -> None:
    loaded = capture(data, [{"t": t, "x": x, "y": 0} for t, x in [(0, 0), (30, 4), (60, 8)]])
    custom = replace(
        params,
        rage_click=replace(
            params.rage_click, min_clicks=3, window_ms=window_ms, radius_px=radius_px
        ),
    )

    assert len(detectors.RageClickDetector().find(loaded, custom)) == count


@pytest.mark.parametrize(
    ("delay", "mutations", "navigated", "dead"),
    [
        (0, 1, False, False),
        (1500, 1, False, False),
        (1501, 1, False, True),
        (100, 0, False, True),
        (100, 0, True, False),
    ],
)
def test_dead_click_response_is_correlated_and_must_arrive_within_the_deadline(
    data: SessionData, params: Parameters, delay: int, mutations: int, navigated: bool, dead: bool
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0},
            {
                "t": delay,
                "type": "click_response",
                "screen": "/destination",
                "data": {"click_t": 0, "mutation_count": mutations, "navigated": navigated},
            },
        ],
    )

    found = detectors.DeadClickDetector().find(loaded, params)

    assert len(found) == int(dead)
    if dead:
        assert found.iloc[0]["screen"] == "/"


def test_responses_and_focus_for_other_clicks_do_not_hide_a_dead_click(
    data: SessionData, params: Parameters
) -> None:
    field = scenarios.SEARCH_INPUT.descriptor()
    loaded = capture(
        data,
        [
            {"t": 0},
            {"t": 100, "element": field},
            {"t": 120, "type": "focus_in", "element": field},
            {
                "t": 130,
                "type": "click_response",
                "data": {"click_t": 100, "mutation_count": 1, "navigated": False},
            },
        ],
    )

    found = detectors.DeadClickDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at]


def test_focusing_editing_and_clicking_an_already_focused_field_are_responses(
    data: SessionData, params: Parameters
) -> None:
    field = scenarios.SEARCH_INPUT.descriptor()
    loaded = capture(
        data,
        [
            {"t": 0, "element": field},
            {"t": 30, "type": "focus_in", "element": field},
            {"t": 100, "element": field},
            {"t": 200, "type": "focus_out", "element": field},
            {"t": 300, "element": field},
            {"t": 350, "type": "field_change", "element": field},
        ],
    )

    assert detectors.DeadClickDetector().find(loaded, params).empty


def test_button_focus_alone_is_not_an_application_response(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0},
            {"t": 30, "type": "focus_in"},
            {"t": 1000},
        ],
    )

    found = detectors.DeadClickDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at, data.session.started_at + 1000]


def test_navigation_without_a_response_is_attributed_to_the_latest_click(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0},
            {"t": 100},
            {
                "t": 200,
                "type": "screen_change",
                "screen": "/next",
                "url": "https://shop.local/next",
            },
        ],
    )

    found = detectors.DeadClickDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at]


@pytest.mark.parametrize("closed", [False, True])
def test_dead_click_requires_a_complete_observation_window(
    data: SessionData, params: Parameters, closed: bool
) -> None:
    loaded = capture(data, [{"t": 0}, {"t": 1000, "type": "mousemove"}])
    loaded = replace(
        loaded,
        session=replace(
            loaded.session, ended_at=data.session.started_at + 1000 if closed else None
        ),
    )

    assert detectors.DeadClickDetector().find(loaded, params).empty
    custom = replace(params, dead_click=replace(params.dead_click, wait_ms=500))
    assert len(detectors.DeadClickDetector().find(loaded, custom)) == 1


def test_both_detectors_preserve_input_and_handle_empty_streams(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, [{"t": t} for t in (0, 100, 200)])
    before = {name: getattr(loaded, name).copy(deep=True) for name in SESSION_FRAMES}

    found = detectors.detect(loaded, params)

    assert set(found["type"]) == {"rage_click", "dead_click"}
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(loaded, name), before[name], check_exact=True)
    empty = replace(data, events=columns.empty("events"))
    assert_frame_equal(detectors.detect(empty, params), columns.empty("incident"), check_exact=True)


def test_clicks_without_an_element_descriptor_can_still_be_detected(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, [{"t": t, "element": None} for t in (0, 100, 200)])

    found = detectors.detect(loaded, params)

    assert found["type"].value_counts().to_dict() == {"dead_click": 3, "rage_click": 1}
    assert found["element"].isna().all()


def test_mock_click_incidents_match_truth_without_false_positives(
    mock: Any, params: Parameters
) -> None:
    with closing(db.open_database(mock.path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in mock.truth["sessions"]:
            loaded = screens.assign_screens(
                cleaning.clean(repository.load_session(session["session_id"]), params), params
            )

            found = detectors.detect(loaded, params)
            found = found[found["type"].isin(("rage_click", "dead_click"))].sort_values(
                ["t", "type"], ignore_index=True
            )

            truth = columns.frame(
                "incident",
                [
                    {
                        "type": item["type"],
                        "t": item["t_start"],
                        "screen": item["screen"],
                        "task_id": item["task_id"],
                        "element": item["element"],
                    }
                    for item in session["incidents"]
                    if item["type"] in ("rage_click", "dead_click")
                ],
            ).sort_values(["t", "type"], ignore_index=True)
            assert_frame_equal(found, truth, check_exact=True, obj=session["key"])


def test_click_incidents_are_saved_and_counted_in_screen_episodes(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.PRODUCT)
        .with_rage_click(scenarios.ADD_TO_CART)
        .with_dead_click(scenarios.ZOOM_BADGE)
        .build()
    )
    loaded = store.load_session(connection, recording)

    result = analyze_session(SqliteAnalysisRepository(connection), loaded.session.id, params)

    assert result.incidents["type"].tolist() == ["rage_click", "dead_click"]
    assert result.episodes[result.episodes["type"] == "screen"].iloc[0]["metrics"] == {
        "incidents": 2
    }
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM incident WHERE session_id = ?", (loaded.session.id,)
        ).fetchone()[0]
        == 2
    )
