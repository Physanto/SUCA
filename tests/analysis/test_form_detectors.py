"""Incidentes de formularios y búsquedas con señales capturables."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import cleaning, columns, detectors, screens
from analysis.loader import SESSION_FRAMES, SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import analyze_session
from scripts.simulation import scenarios, store
from scripts.simulation.builder import Click, FillForm, SessionBuilder
from shared import db

KINDS = ("form_error", "field_reentry", "form_abandonment", "repeated_search")


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Sesión base para eventos con límites controlados."""
    return repository.load_session(1)


def capture(data: SessionData, records: list[dict]) -> SessionData:
    """Usa tiempos relativos y conserva solo descriptores, sin valores de los campos."""
    return replace(
        data,
        events=columns.frame(
            "events",
            [
                {
                    "type": "field_change",
                    "url": "https://shop.local/",
                    "title": "Tienda",
                    "screen": "/",
                    "element": scenarios.SHIP_NAME.descriptor(),
                    **item,
                    "t": data.session.started_at + item["t"],
                }
                for item in records
            ],
        ),
    )


@pytest.mark.parametrize("kind", KINDS)
def test_builder_patterns_match_their_incident_truth(
    connection: sqlite3.Connection, params: Parameters, kind: str
) -> None:
    builder = SessionBuilder(study_id=1, camera=False)
    if kind in ("form_error", "field_reentry"):
        builder.on_screen(scenarios.SHIPPING).with_form_error(0, times=2, erases=True).do(
            FillForm(
                scenarios.SHIP_FORM,
                (scenarios.SHIP_NAME, scenarios.SHIP_ADDRESS),
                scenarios.SHIP_SUBMIT,
                to=scenarios.PAYMENT,
            )
        )
    elif kind == "form_abandonment":
        builder.on_screen(scenarios.CART).with_form_abandonment(
            scenarios.NEWSLETTER, Click(scenarios.NAV_HOME, to=scenarios.HOME)
        )
    else:
        builder.on_screen(scenarios.HOME).with_repeated_search(
            scenarios.SEARCH, [scenarios.results("uno"), scenarios.results("dos")]
        )
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
                "t": item.t_end if kind == "repeated_search" else item.t_start,
                "screen": item.screen,
                "task_id": item.task_id,
                "element": item.element,
            }
            for item in recording.truth.incidents
            if item.type == kind
        ],
    )
    assert not truth.empty
    assert_frame_equal(found, truth, check_exact=True)


def test_form_error_requires_an_explicit_validation_event(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [{"t": 0}, {"t": 100, "type": "form_submit", "element": scenarios.SHIP_FORM.descriptor()}],
    )

    assert detectors.FormErrorDetector().find(loaded, params).empty
    errors = capture(
        data,
        [
            {"t": t, "type": "validation_error", "data": {"error_type": kind}}
            for t, kind in enumerate(("value_missing", "aria_invalid", "visible_message"))
        ],
    )
    assert len(detectors.FormErrorDetector().find(errors, params)) == 3


@pytest.mark.parametrize("change", [False, True])
def test_field_reentry_requires_editing_after_returning_focus(
    data: SessionData, params: Parameters, change: bool
) -> None:
    records = [{"t": 0}, {"t": 10}, {"t": 20, "type": "focus_out"}, {"t": 30, "type": "focus_in"}]
    if change:
        records += [{"t": 40}, {"t": 50}]

    found = detectors.FieldReentryDetector().find(capture(data, records), params)

    assert found["t"].tolist() == ([data.session.started_at + 30] if change else [])


@pytest.mark.parametrize("boundary", ["task", "url", "submit"])
def test_field_reentry_does_not_cross_new_form_contexts(
    data: SessionData, params: Parameters, boundary: str
) -> None:
    records = [{"t": 0}, {"t": 10, "type": "focus_out"}]
    extra = (
        {"task_id": 2}
        if boundary == "task"
        else {"url": "https://shop.local/other"}
        if boundary == "url"
        else {}
    )
    if boundary == "submit":
        records.append(
            {"t": 20, "type": "form_submit", "element": scenarios.SHIP_FORM.descriptor()}
        )
    records += [{"t": 30, "type": "focus_in", **extra}, {"t": 40, **extra}]

    assert detectors.FieldReentryDetector().find(capture(data, records), params).empty


def test_field_reentry_does_not_treat_a_continuous_edit_as_multiple_visits(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": t, "type": kind}
            for t, kind in enumerate(
                ("focus_in", "field_change", "click", "focus_in", "field_change")
            )
        ],
    )

    assert detectors.FieldReentryDetector().find(loaded, params).empty


@pytest.mark.parametrize(
    ("submitted", "closed", "expected"), [(False, False, 0), (False, True, 1), (True, True, 0)]
)
def test_form_abandonment_requires_an_observed_exit_or_session_end(
    data: SessionData, params: Parameters, submitted: bool, closed: bool, expected: int
) -> None:
    records = [{"t": 0}]
    if submitted:
        records.append(
            {"t": 100, "type": "form_submit", "element": scenarios.SHIP_FORM.descriptor()}
        )
    loaded = capture(data, records)
    loaded = replace(
        loaded,
        session=replace(loaded.session, ended_at=data.session.started_at + 500 if closed else None),
    )

    assert len(detectors.FormAbandonmentDetector().find(loaded, params)) == expected


def test_focusing_a_field_without_editing_is_not_form_abandonment(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data, [{"t": 0, "type": "focus_in"}, {"t": 100, "type": "screen_change", "screen": "/away"}]
    )

    assert detectors.FormAbandonmentDetector().find(loaded, params).empty


def search_events(times: list[int], **extra: Any) -> list[dict]:
    """Una reformulación por envío, separada por cambios en el campo de búsqueda."""
    return [
        event
        for time in times
        for event in (
            {"t": time - 1, "element": scenarios.SEARCH_INPUT.descriptor(), **extra},
            {
                "t": time,
                "type": "form_submit",
                "element": scenarios.SEARCH_FORM.descriptor(),
                **extra,
            },
        )
    ]


@pytest.mark.parametrize(
    ("times", "minimum", "expected"),
    [
        ([1], 2, []),
        ([1, 1001], 2, [1001]),
        ([1, 1002], 2, []),
        ([1, 500, 1001], 3, [1001]),
        ([1, 500], 3, []),
        ([1, 500, 1000, 1500], 2, [500]),
        ([1, 500, 2000, 2500], 2, [500, 2500]),
    ],
)
def test_repeated_search_window_threshold_and_burst_deduplication(
    data: SessionData, params: Parameters, times: list[int], minimum: int, expected: list[int]
) -> None:
    settings = replace(
        params,
        repeated_search=replace(params.repeated_search, min_searches=minimum, window_ms=1000),
    )

    found = detectors.RepeatedSearchDetector().find(capture(data, search_events(times)), settings)

    assert found["t"].tolist() == [data.session.started_at + t for t in expected]


@pytest.mark.parametrize("boundary", ["result", "navigation", "task", "other_form"])
def test_repeated_search_does_not_join_separate_search_activities(
    data: SessionData, params: Parameters, boundary: str
) -> None:
    middle = {"t": 500, "type": "click", "element": scenarios.RESULT_1.descriptor()}
    extra = {}
    if boundary == "navigation":
        middle = {"t": 500, "type": "screen_change", "screen": "/elsewhere"}
    elif boundary == "task":
        extra = {"task_id": 2}
        middle = {"t": 500, "type": "mousemove", "element": None, **extra}
    elif boundary == "other_form":
        middle = {"t": 500, "element": scenarios.NEWSLETTER_EMAIL.descriptor()}
    loaded = capture(data, search_events([1]) + [middle] + search_events([1001], **extra))

    assert detectors.RepeatedSearchDetector().find(loaded, params).empty


def test_repeated_search_does_not_count_duplicate_submit_events_as_queries(
    data: SessionData, params: Parameters
) -> None:
    records = search_events([1]) + [
        {"t": 10, "type": "form_submit", "element": scenarios.SEARCH_FORM.descriptor()}
    ]

    assert detectors.RepeatedSearchDetector().find(capture(data, records), params).empty


def test_repeated_search_handles_enter_submissions_without_click_responses(
    data: SessionData, params: Parameters
) -> None:
    first = {"url": "https://shop.local/search?q=one", "screen": "/search"}
    second = {"url": "https://shop.local/search?q=two", "screen": "/search"}
    records = (
        search_events([1])
        + [{"t": 100, "type": "screen_change", "element": None, **first}]
        + search_events([1001], **first)
        + [{"t": 1100, "type": "screen_change", "element": None, **second}]
    )

    found = detectors.RepeatedSearchDetector().find(capture(data, records), params)

    assert found["t"].tolist() == [data.session.started_at + 1001]
    assert found["screen"].tolist() == ["/search"]


def test_detectors_preserve_nested_input_and_accept_empty_streams(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(data, search_events([1, 1001]))
    snapshots = {
        name: columns.frame(name, deepcopy(getattr(loaded, name).to_dict("records")))
        for name in SESSION_FRAMES
    }
    for kind in KINDS:
        detectors.DETECTORS.get(kind).find(loaded, params)
        for name in SESSION_FRAMES:
            assert_frame_equal(getattr(loaded, name), snapshots[name], check_exact=True)
    empty = replace(loaded, events=columns.empty("events"))
    for kind in KINDS:
        assert_frame_equal(
            detectors.DETECTORS.get(kind).find(empty, params),
            columns.empty("incident"),
            check_exact=True,
        )


def test_mock_form_incidents_match_truth_without_false_positives(
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

            expected = columns.frame(
                "incident",
                [
                    {
                        "type": item["type"],
                        "t": item["t_end"]
                        if item["type"] == "repeated_search"
                        else item["t_start"],
                        "screen": item["screen"],
                        "task_id": item["task_id"],
                        "element": item["element"],
                    }
                    for item in session["incidents"]
                    if item["type"] in KINDS
                ],
            ).sort_values(["t", "type"], ignore_index=True)
            assert_frame_equal(found, expected, check_exact=True, obj=session["key"])


def test_form_incidents_are_saved_and_counted_in_the_pipeline(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.LOGIN)
        .with_form_error(0)
        .do(scenarios.LOGIN_ACTION)
        .build()
    )
    loaded = store.load_session(connection, recording)

    result = analyze_session(SqliteAnalysisRepository(connection), loaded.session.id, params)

    assert set(result.incidents["type"]) == {"form_error", "field_reentry"}
    assert (
        sum(
            row["incidents"]
            for row in result.episodes[result.episodes["type"] == "screen"]["metrics"]
        )
        == 2
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM incident WHERE session_id = ?", (loaded.session.id,)
        ).fetchone()[0]
        == 2
    )
