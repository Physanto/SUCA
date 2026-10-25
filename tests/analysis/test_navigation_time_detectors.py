"""Pruebas de navegación, inactividad, vacilación y duración de tareas."""

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
from scripts.simulation.builder import Click, SessionBuilder
from shared import db

KINDS = ("navigation_loop", "long_pause", "hesitation", "task_overtime")


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Sesión base para construir señales con tiempos controlados."""
    return repository.load_session(1)


def capture(data: SessionData, records: list[dict]) -> SessionData:
    """Construye eventos relativos al inicio de la sesión."""
    return replace(
        data,
        events=columns.frame(
            "events",
            [
                {
                    "type": "mousemove",
                    "x": 5,
                    "y": 5,
                    "url": "https://shop.local/",
                    "title": "Inicio",
                    "screen": "/",
                    **record,
                    "t": data.session.started_at + record["t"],
                }
                for record in records
            ],
        ),
    )


def references(data: SessionData, durations: list[float | None]) -> SessionData:
    """Referencias confirmadas de la tarea uno, con duraciones explícitas."""
    return replace(
        data,
        references=columns.frame(
            "references",
            [
                {
                    "id": index + 1,
                    "task_id": 1,
                    "steps": [],
                    "required_steps": [],
                    "end_condition": None,
                    "duration_ms": duration,
                }
                for index, duration in enumerate(durations)
            ],
        ),
    )


def task(data: SessionData, duration: float) -> SessionData:
    """Una tarea guiada terminada, sin cambiar sus eventos."""
    start = data.session.started_at
    return replace(
        data,
        tasks=columns.frame(
            "tasks",
            [{"task_id": 1, "t_start": start, "t_end": start + duration, "ended_by": "done"}],
        ),
    )


@pytest.mark.parametrize("kind", KINDS)
def test_builder_patterns_match_their_incident_truth(
    connection: sqlite3.Connection, params: Parameters, kind: str
) -> None:
    builder = SessionBuilder(
        study_id=1,
        camera=False,
        mode="guided" if kind == "task_overtime" else "free",
        reference_durations={1: 1000},
    ).on_screen(scenarios.HOME)
    if kind == "navigation_loop":
        builder.with_navigation_loop(
            Click(scenarios.NAV_OFFERS, to=scenarios.OFFERS),
            Click(scenarios.NAV_HOME, to=scenarios.HOME),
        )
    elif kind == "long_pause":
        builder.do(Click(scenarios.CART_LINK, to=scenarios.CART)).with_long_pause().do(
            Click(scenarios.NAV_HOME, to=scenarios.HOME)
        )
    elif kind == "hesitation":
        builder.with_hesitation(scenarios.CART_LINK).do(
            Click(scenarios.CART_LINK, to=scenarios.CART)
        )
    else:
        builder.with_task(
            1, (Click(scenarios.CART_LINK, to=scenarios.CART),)
        ).with_overtime().end_task("gave_up")
    recording = builder.build()
    loaded = store.load_session(connection, recording)
    if kind == "task_overtime":
        loaded = references(loaded, [1000])
    loaded = screens.assign_screens(cleaning.clean(loaded, params), params)

    found = detectors.DETECTORS.get(kind).find(loaded, params)

    truth = columns.frame(
        "incident",
        [
            {
                "type": item.type,
                "t": item.t_end if kind == "navigation_loop" else item.t_start,
                "screen": item.screen,
                "task_id": item.task_id,
                "element": item.element,
            }
            for item in recording.truth.incidents
            if item.type == kind
        ],
    )
    assert not truth.empty
    assert_frame_equal(found, truth, check_exact=False, rtol=0, atol=0.1)


@pytest.mark.parametrize(
    ("pages", "window", "expected"),
    [
        (["/a", "/b", "/a"], 3, [200]),
        (["/a", "/b", "/c"], 3, []),
        (["/a", "/a", "/a"], 3, []),
        (["/a", "/b", "/c", "/a"], 3, []),
        (["/a", "/b", "/c", "/a"], 4, [300]),
        (["/a", "/b", "/a"], 2, []),
    ],
)
def test_navigation_loop_collapses_visits_and_honors_the_window(
    data: SessionData, params: Parameters, pages: list[str], window: int, expected: list[int]
) -> None:
    loaded = capture(
        data,
        [
            {"t": index * 100, "type": "screen_change", "screen": page}
            for index, page in enumerate(pages)
        ],
    )

    found = detectors.NavigationLoopDetector().find(
        loaded, replace(params, navigation_loop_window=window)
    )

    assert found["t"].tolist() == [data.session.started_at + t for t in expected]
    if expected:
        assert found["screen"].tolist() == ["/a"]


def test_navigation_loop_does_not_cross_task_boundaries(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0, "screen": "/a", "task_id": 1},
            {"t": 100, "screen": "/b", "task_id": 1},
            {"t": 200, "screen": "/a", "task_id": 2},
        ],
    )

    assert detectors.NavigationLoopDetector().find(loaded, params).empty


@pytest.mark.parametrize("duration", [4999, 5000, 5001])
def test_long_pause_uses_a_strict_threshold(
    data: SessionData, params: Parameters, duration: int
) -> None:
    loaded = capture(data, [{"t": 0}, {"t": duration}])

    found = detectors.LongPauseDetector().find(loaded, replace(params, long_pause_ms=5000))

    assert len(found) == int(duration > 5000)
    if not found.empty:
        assert found.iloc[0]["t"] == data.session.started_at
        assert found.iloc[0]["element"] is None


def test_camera_gaps_do_not_count_as_interaction_or_fabricate_a_trailing_pause(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, [{"t": 0}, {"t": 3000, "type": "camera_gap"}, {"t": 6000}])

    found = detectors.LongPauseDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at]
    assert detectors.LongPauseDetector().find(capture(data, [{"t": 0}]), params).empty


def test_long_pause_does_not_combine_separate_tasks(data: SessionData, params: Parameters) -> None:
    loaded = capture(data, [{"t": 0, "task_id": 1}, {"t": 6000, "task_id": 2}])

    assert detectors.LongPauseDetector().find(loaded, params).empty


@pytest.mark.parametrize("duration", [1999, 2000, 2001])
def test_hesitation_requires_stationary_pointer_over_a_known_interactive_element(
    data: SessionData, params: Parameters, duration: int
) -> None:
    button = scenarios.ADD_TO_CART.descriptor()
    loaded = capture(
        data,
        [
            {"t": 0, "x": 750, "y": 440},
            {"t": duration, "type": "click", "x": 750, "y": 440, "element": button},
        ],
    )
    loaded = replace(
        loaded, session=replace(loaded.session, ended_at=data.session.started_at + duration)
    )

    found = detectors.HesitationDetector().find(loaded, replace(params, hesitation_ms=2000))

    assert len(found) == int(duration > 2000)
    if not found.empty:
        assert found.iloc[0]["t"] == data.session.started_at
        assert found.iloc[0]["element"]["selector"] == button["selector"]


def test_hesitation_is_not_inferred_without_a_known_element(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, [{"t": 0, "x": 750, "y": 440}, {"t": 3000, "x": 750, "y": 440}])
    loaded = replace(loaded, references=columns.empty("references"))

    assert detectors.HesitationDetector().find(loaded, params).empty


def test_movement_and_an_already_activated_element_are_not_hesitation(
    data: SessionData, params: Parameters
) -> None:
    button = scenarios.ADD_TO_CART.descriptor()
    loaded = capture(
        data,
        [
            {"t": 0, "type": "click", "x": 750, "y": 440, "element": button},
            {"t": 100, "x": 751, "y": 440},
            {"t": 3100, "x": 752, "y": 440},
        ],
    )

    assert detectors.HesitationDetector().find(loaded, params).empty
    moving = capture(
        data,
        [{"t": t, "x": 750 + t / 1000, "y": 440, "element": button} for t in (0, 1000, 2000, 3000)],
    )
    moving = replace(
        moving, session=replace(moving.session, ended_at=data.session.started_at + 3000)
    )
    assert detectors.HesitationDetector().find(moving, params).empty


def test_scrolling_invalidates_a_pending_hesitation(data: SessionData, params: Parameters) -> None:
    button = scenarios.ADD_TO_CART.descriptor()
    loaded = capture(
        data,
        [
            {"t": 0, "x": 750, "y": 440, "element": button},
            {"t": 1000, "type": "scroll", "data": {"scroll_x": 0, "scroll_y": 500}},
            {
                "t": 4000,
                "type": "click_response",
                "data": {
                    "click_t": data.session.started_at,
                    "mutation_count": 1,
                    "navigated": False,
                },
            },
        ],
    )

    assert detectors.HesitationDetector().find(loaded, params).empty


@pytest.mark.parametrize(("duration", "expected"), [(2999, 0), (3000, 0), (3001, 1)])
def test_task_overtime_requires_exceeding_the_reference_factor(
    data: SessionData, params: Parameters, duration: int, expected: int
) -> None:
    loaded = task(references(capture(data, [{"t": 0, "task_id": 1}]), [1000]), duration)

    found = detectors.TaskOvertimeDetector().find(loaded, replace(params, task_overtime_factor=3))

    assert len(found) == expected
    if expected:
        assert found.iloc[0]["t"] == data.session.started_at + 3000
        assert found.iloc[0]["task_id"] == 1


def test_task_overtime_uses_the_longest_valid_reference_and_screen_at_the_deadline(
    data: SessionData, params: Parameters
) -> None:
    loaded = task(
        references(
            capture(
                data,
                [
                    {"t": 0, "screen": "/a", "task_id": 1},
                    {"t": 5500, "screen": "/b", "task_id": 1},
                    {"t": 6500, "screen": "/c", "task_id": 1},
                ],
            ),
            [None, 0, 1000, 2000],
        ),
        7000,
    )

    found = detectors.TaskOvertimeDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at + 6000]
    assert found["screen"].tolist() == ["/b"]


@pytest.mark.parametrize("mode", ["free", "reference"])
def test_task_overtime_does_not_evaluate_other_session_modes(
    data: SessionData, params: Parameters, mode: str
) -> None:
    loaded = task(references(data, [1000]), 10000)
    loaded = replace(loaded, session=replace(loaded.session, mode=mode))

    assert detectors.TaskOvertimeDetector().find(loaded, params).empty


def test_task_overtime_skips_missing_references(data: SessionData, params: Parameters) -> None:
    loaded = task(references(data, [None, 0]), 10000)

    assert detectors.TaskOvertimeDetector().find(loaded, params).empty


def test_hesitation_can_use_a_reference_for_an_element_never_clicked(
    data: SessionData, params: Parameters
) -> None:
    button = scenarios.ADD_TO_CART.descriptor()
    loaded = references(capture(data, [{"t": 0, "x": 750, "y": 440}, {"t": 3000}]), [1000])
    loaded.references.at[0, "steps"] = [
        {
            "t": data.session.started_at,
            "type": "click",
            "element": button,
            "screen": {"url": "https://shop.local/", "title": "Inicio"},
        }
    ]

    found = detectors.HesitationDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at]
    assert found.iloc[0]["element"] == button


@pytest.mark.parametrize("interactive", [False, True])
def test_hesitation_requires_a_hit_inside_an_interactive_rectangle(
    data: SessionData, params: Parameters, interactive: bool
) -> None:
    button = {**scenarios.ADD_TO_CART.descriptor(), "interactive": interactive}
    loaded = capture(
        data, [{"t": 0, "x": 941 if interactive else 750, "y": 440, "element": button}, {"t": 3000}]
    )

    assert detectors.HesitationDetector().find(loaded, params).empty


def test_hesitation_does_not_duplicate_identical_pointer_samples(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": t, "x": 750, "y": 440, "element": scenarios.ADD_TO_CART.descriptor()}
            for t in (0, 1000, 2100, 4000)
        ],
    )

    found = detectors.HesitationDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at]


def test_hesitation_does_not_cross_tasks(data: SessionData, params: Parameters) -> None:
    loaded = capture(
        data,
        [
            {
                "t": t,
                "task_id": index + 1,
                "x": 750,
                "y": 440,
                "element": scenarios.ADD_TO_CART.descriptor(),
            }
            for index, t in enumerate((0, 3000))
        ],
    )
    loaded = replace(
        loaded, session=replace(loaded.session, ended_at=data.session.started_at + 3000)
    )

    assert detectors.HesitationDetector().find(loaded, params).empty


def test_hesitation_uses_page_coordinates_after_scrolling(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0, "x": 750, "y": 440, "element": scenarios.ADD_TO_CART.descriptor()},
            {"t": 1000, "type": "scroll", "data": {"scroll_x": 0, "scroll_y": 200}},
            {"t": 1100, "x": 750, "y": 240},
            {"t": 4100, "type": "click_response"},
        ],
    )

    found = detectors.HesitationDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at + 1100]
    assert found.iloc[0]["element"]["box"]["y"] == 220


def test_later_layout_changes_do_not_replace_the_geometry_at_the_hover(
    data: SessionData, params: Parameters
) -> None:
    button = scenarios.ADD_TO_CART.descriptor()
    moved = {**button, "box": {**button["box"], "y": 700}}
    loaded = capture(
        data,
        [
            {"t": 0, "x": 750, "y": 440, "element": button},
            {"t": 3000, "x": 0, "y": 0, "element": moved},
        ],
    )

    found = detectors.HesitationDetector().find(loaded, params)

    assert found["t"].tolist() == [data.session.started_at]
    assert found.iloc[0]["element"] == button


def test_an_open_session_does_not_use_camera_gaps_as_the_hesitation_horizon(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0, "x": 750, "y": 440, "element": scenarios.ADD_TO_CART.descriptor()},
            {"t": 5000, "type": "camera_gap"},
        ],
    )
    loaded = replace(loaded, session=replace(loaded.session, ended_at=None))

    assert detectors.HesitationDetector().find(loaded, params).empty


def test_detectors_preserve_input_and_accept_empty_session_data(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, [{"t": 0}, {"t": 6000}])
    before = {name: getattr(loaded, name).copy(deep=True) for name in SESSION_FRAMES}
    for kind in KINDS:
        detectors.DETECTORS.get(kind).find(loaded, params)
        for name in SESSION_FRAMES:
            assert_frame_equal(getattr(loaded, name), before[name], check_exact=True)
    empty = replace(
        loaded,
        events=columns.empty("events"),
        tasks=columns.empty("tasks"),
        references=columns.empty("references"),
    )
    for kind in KINDS:
        assert_frame_equal(
            detectors.DETECTORS.get(kind).find(empty, params),
            columns.empty("incident"),
            check_exact=True,
        )


def test_mock_navigation_and_time_incidents_match_truth_without_false_positives(
    mock: Any, params: Parameters
) -> None:
    with closing(db.open_database(mock.path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in mock.truth["sessions"]:
            loaded = screens.assign_screens(
                cleaning.clean(repository.load_session(session["session_id"]), params), params
            )

            found = detectors.detect(loaded, params)
            found = found[found["type"].isin(KINDS)].sort_values(["t", "type"], ignore_index=True)

            truth = columns.frame(
                "incident",
                [
                    {
                        "type": item["type"],
                        "t": item["t_end"]
                        if item["type"] == "navigation_loop"
                        else item["t_start"],
                        "screen": item["screen"],
                        "task_id": item["task_id"],
                        "element": item["element"],
                    }
                    for item in session["incidents"]
                    if item["type"] in KINDS
                ],
            ).sort_values(["t", "type"], ignore_index=True)
            assert_frame_equal(
                found, truth, check_exact=False, rtol=0, atol=0.1, obj=session["key"]
            )


def test_navigation_and_pause_are_saved_and_counted_per_screen(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.HOME)
        .with_navigation_loop(
            Click(scenarios.NAV_OFFERS, to=scenarios.OFFERS),
            Click(scenarios.NAV_HOME, to=scenarios.HOME),
        )
        .with_long_pause()
        .do(Click(scenarios.CART_LINK, to=scenarios.CART))
        .build()
    )
    loaded = store.load_session(connection, recording)

    result = analyze_session(SqliteAnalysisRepository(connection), loaded.session.id, params)

    assert set(result.incidents["type"]) == {"navigation_loop", "long_pause"}
    assert sum(row["incidents"] for row in result.episodes["metrics"]) == len(result.incidents)
    assert connection.execute(
        "SELECT COUNT(*) FROM incident WHERE session_id = ?", (loaded.session.id,)
    ).fetchone()[0] == len(result.incidents)
