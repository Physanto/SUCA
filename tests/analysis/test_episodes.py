"""Pruebas de episodios observables, métricas y comparación con datos simulados."""

import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import cleaning, columns, detectors, episodes, screens
from analysis.loader import SESSION_FRAMES, SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from scripts.simulation import scenarios, store
from scripts.simulation.builder import Click, FillForm, SessionBuilder, SimulatedSession
from shared import db


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Sesión con los DataFrames base para los casos de límites."""
    return repository.load_session(1)


def prepare(data: SessionData, params: Parameters) -> SessionData:
    """Ejecuta las etapas que preceden a episodios."""
    return screens.assign_screens(cleaning.clean(data, params), params)


def expected(recording: SimulatedSession, kind: str) -> Any:
    """Filas esperadas del constructor para un único tipo de episodio."""
    return columns.frame(
        "episode", [asdict(item) for item in recording.truth.episodes if item.type == kind]
    )


def capture(data: SessionData, records: list[dict]) -> SessionData:
    """Construye eventos con tiempos relativos al inicio de la sesión."""
    return replace(
        data,
        events=columns.frame(
            "events",
            [
                {
                    "url": "https://shop.local" + item.get("screen", "/"),
                    "title": "Tienda",
                    "screen": "/",
                    **item,
                    "t": data.session.started_at + item["t"],
                }
                for item in records
            ],
        ),
    )


@pytest.mark.parametrize("kind", ["login", "form", "search", "screen"])
def test_each_detector_matches_a_positive_builder_case(
    connection: sqlite3.Connection, params: Parameters, kind: str
) -> None:
    builder = SessionBuilder(study_id=1, camera=False).on_screen(scenarios.LOGIN)
    if kind == "login":
        builder.do(scenarios.LOGIN_ACTION)
    elif kind == "form":
        builder.on_screen(scenarios.ACCOUNT).do(scenarios.TASKS[3].path[-1])
    elif kind == "search":
        builder.do(scenarios.SEARCH, Click(scenarios.RESULT_1, to=scenarios.PRODUCT))
    else:
        builder.do(Click(scenarios.CART_LINK, to=scenarios.CART))
    recording = builder.build()
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.EPISODE_DETECTORS.get(kind).find(loaded, params)

    assert not found.empty
    assert_frame_equal(found, expected(recording, kind), check_exact=True)


@pytest.mark.parametrize("kind", ["login", "form", "search", "screen"])
def test_each_detector_rejects_unrelated_events(
    data: SessionData, params: Parameters, kind: str
) -> None:
    if kind == "screen":
        records = [{"t": 0, "type": "camera_gap", "data": {"t_end": None, "reason": "error"}}]
    elif kind == "form":
        records = [{"t": 0, "type": "click", "element": scenarios.PAY_CARD.descriptor()}]
    else:
        records = [{"t": 0, "type": "focus_in", "element": scenarios.ADDRESS_FIELD.descriptor()}]

    found = episodes.EPISODE_DETECTORS.get(kind).find(capture(data, records), params)

    assert_frame_equal(found, columns.empty("episode"), check_exact=True)


@pytest.mark.parametrize("kind", ["login", "form"])
def test_validation_errors_and_reentries_are_counted_once_per_field_visit(
    connection: sqlite3.Connection, params: Parameters, kind: str
) -> None:
    action = (
        scenarios.LOGIN_ACTION
        if kind == "login"
        else FillForm(
            scenarios.SHIP_FORM,
            (scenarios.SHIP_NAME, scenarios.SHIP_ADDRESS),
            scenarios.SHIP_SUBMIT,
            to=scenarios.PAYMENT,
        )
    )
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.LOGIN if kind == "login" else scenarios.SHIPPING)
        .with_form_error(0, times=2, erases=True)
        .do(action)
        .build()
    )
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.EPISODE_DETECTORS.get(kind).find(loaded, params)

    assert_frame_equal(found, expected(recording, kind), check_exact=True)


def test_form_abandonment_ends_at_the_leaving_click(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.CART)
        .with_form_abandonment(scenarios.NEWSLETTER, Click(scenarios.NAV_HOME, to=scenarios.HOME))
        .build()
    )
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.FormEpisodes().find(loaded, params)

    assert_frame_equal(found, expected(recording, "form"), check_exact=True)


def test_forms_on_the_same_screen_keep_separate_metrics(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    address = FillForm(scenarios.ADDRESS_FORM, (scenarios.ADDRESS_FIELD,), scenarios.ADDRESS_SAVE)
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.HOME)
        .do(scenarios.NEWSLETTER, address)
        .build()
    )
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.FormEpisodes().find(loaded, params)

    assert len(found) == 2
    assert_frame_equal(found, expected(recording, "form"), check_exact=True)


def test_failed_login_is_not_reported_as_success(data: SessionData, params: Parameters) -> None:
    loaded = capture(
        data,
        [
            {"t": 0, "type": "focus_in", "element": scenarios.LOGIN_PASSWORD.descriptor()},
            {"t": 10, "type": "field_change", "element": scenarios.LOGIN_PASSWORD.descriptor()},
            {"t": 20, "type": "form_submit", "element": scenarios.LOGIN_FORM.descriptor()},
            {"t": 30, "type": "validation_error", "element": scenarios.LOGIN_PASSWORD.descriptor()},
            {"t": 40, "type": "click", "element": scenarios.NAV_HOME.descriptor()},
            {"t": 50, "type": "screen_change", "screen": "/help"},
        ],
    )

    found = episodes.LoginEpisodes().find(loaded, params)

    assert found["outcome"].tolist() == ["failed"]
    assert found.iloc[0]["metrics"] == {"attempts": 1, "errors": 1}


@pytest.mark.parametrize("selector", ["#nav-home", "#nav_home", "nav a"])
def test_search_does_not_count_a_navigation_link_as_a_result(
    connection: sqlite3.Connection, params: Parameters, selector: str
) -> None:
    navigation = replace(scenarios.NAV_HOME, id=None, selector=selector)
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.HOME)
        .do(scenarios.SEARCH, Click(navigation, to=scenarios.HOME))
        .build()
    )
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.SearchEpisodes().find(loaded, params)

    assert found["outcome"].tolist() == ["no_result_opened"]
    assert found.iloc[0]["metrics"] == {"searches": 1, "result_clicks": 0}


def test_screen_visits_use_half_open_intervals_and_preserve_input(
    data: SessionData, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0, "type": "screen_change", "screen": "/a"},
            {"t": 20, "type": "screen_change", "screen": "/a"},
            {"t": 30, "type": "screen_change", "screen": "/b"},
            {"t": 40, "type": "screen_change", "screen": "/a"},
        ],
    )
    known = columns.frame(
        "incident",
        [
            {"type": "dead_click", "t": data.session.started_at + t, "screen": screen}
            for t, screen in [(0, "/a"), (30, "/a"), (30, "/b"), (40, "/a"), (60000, "/a")]
        ],
    )
    monkeypatch.setattr(detectors, "detect", lambda data, params: known)
    before = {name: getattr(loaded, name).copy(deep=True) for name in SESSION_FRAMES}

    found = episodes.ScreenEpisodes().find(loaded, params)

    assert found["screen"].tolist() == ["/a", "/b", "/a"]
    assert found["t_start"].tolist() == [data.session.started_at + t for t in (0, 30, 40)]
    assert found["t_end"].tolist() == [data.session.started_at + t for t in (30, 40, 60000)]
    assert found["metrics"].tolist() == [{"incidents": 1}] * 3
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(loaded, name), before[name], check_exact=True)


def test_empty_session_has_no_episodes(data: SessionData, params: Parameters) -> None:
    loaded = replace(data, events=columns.empty("events"))

    found = episodes.detect(loaded, params)

    assert_frame_equal(found, columns.empty("episode"), check_exact=True)


@pytest.mark.parametrize("kind", ["login", "form", "search"])
def test_focus_out_alone_does_not_start_an_episode(
    data: SessionData, params: Parameters, kind: str
) -> None:
    loaded = capture(
        data, [{"t": 10, "type": "focus_out", "element": scenarios.LOGIN_PASSWORD.descriptor()}]
    )

    found = episodes.EPISODE_DETECTORS.get(kind).find(loaded, params)

    assert_frame_equal(found, columns.empty("episode"), check_exact=True)


def test_validation_and_resubmission_with_equal_times_keep_event_order(
    data: SessionData, params: Parameters
) -> None:
    field = scenarios.LOGIN_PASSWORD.descriptor()
    form = scenarios.LOGIN_FORM.descriptor()
    loaded = capture(
        data,
        [
            {"t": 0, "type": "field_change", "element": field},
            {"t": 10, "type": "form_submit", "element": form},
            {"t": 20, "type": "validation_error", "element": field},
            {"t": 20, "type": "field_change", "element": field},
            {"t": 20, "type": "form_submit", "element": form},
            {"t": 30, "type": "screen_change", "screen": "/home"},
        ],
    )

    found = episodes.LoginEpisodes().find(loaded, params)

    assert found["outcome"].tolist() == ["success"]
    assert found.iloc[0]["metrics"] == {"attempts": 2, "errors": 1}


def test_an_open_session_uses_its_last_observed_event(
    data: SessionData, params: Parameters
) -> None:
    field = scenarios.ADDRESS_FIELD.descriptor()
    loaded = capture(
        replace(data, session=replace(data.session, ended_at=None)),
        [
            {"t": 10, "type": "focus_in", "element": field},
            {"t": 20, "type": "field_change", "element": field},
        ],
    )

    found = episodes.FormEpisodes().find(loaded, params)

    assert found["t_end"].tolist() == [data.session.started_at + 20]
    assert found["outcome"].tolist() == ["abandoned"]


def test_programmatic_navigation_does_not_reuse_an_unrelated_earlier_click(
    data: SessionData, params: Parameters
) -> None:
    loaded = capture(
        data,
        [
            {"t": 0, "type": "click", "element": scenarios.ADDRESS_SAVE.descriptor()},
            {"t": 10, "type": "focus_in", "element": scenarios.ADDRESS_FIELD.descriptor()},
            {"t": 20, "type": "field_change", "element": scenarios.ADDRESS_FIELD.descriptor()},
            {"t": 30, "type": "screen_change", "screen": "/other"},
        ],
    )

    found = episodes.FormEpisodes().find(loaded, params)

    assert found["t_start"].tolist() == [data.session.started_at + 10]
    assert found["t_end"].tolist() == [data.session.started_at + 30]


def test_subsequent_successful_submissions_of_one_form_are_separate_episodes(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.HOME)
        .do(scenarios.NEWSLETTER, scenarios.NEWSLETTER)
        .build()
    )
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.FormEpisodes().find(loaded, params)

    assert_frame_equal(found, expected(recording, "form"), check_exact=True)


def test_result_clicks_separate_search_episodes_even_without_navigation(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    search = replace(scenarios.SEARCH, to=scenarios.HOME)
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.HOME)
        .do(search, Click(scenarios.RESULT_1), search, Click(scenarios.RESULT_1))
        .build()
    )
    loaded = prepare(store.load_session(connection, recording), params)

    found = episodes.SearchEpisodes().find(loaded, params)

    assert_frame_equal(found, expected(recording, "search"), check_exact=True)


def test_mock_episodes_match_truth_with_supplied_incidents(
    mock: Any, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    with closing(db.open_database(mock.path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in mock.truth["sessions"]:
            known = columns.frame(
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
                ],
            )
            monkeypatch.setattr(detectors, "detect", lambda data, params, known=known: known)
            loaded = prepare(repository.load_session(session["session_id"]), params)

            found = episodes.detect(loaded, params).sort_values(
                ["t_start", "type"], ignore_index=True
            )

            truth = columns.frame("episode", session["episodes"]).sort_values(
                ["t_start", "type"], ignore_index=True
            )
            assert_frame_equal(found, truth, check_exact=True, obj=session["key"])
