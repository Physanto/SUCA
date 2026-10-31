"""Pruebas de limpieza, reenvíos de lotes y sincronización de cámara."""

import sqlite3
from dataclasses import replace

import pytest
from pandas.testing import assert_frame_equal

from analysis import cleaning, columns
from analysis.loader import SESSION_FRAMES, SessionData, validate_session_data
from analysis.parameters import Parameters
from scripts.simulation import store
from scripts.simulation.builder import Element, Screen, SessionBuilder, SimulatedSession

STREAMS = ("events", "gaze", "face")


@pytest.fixture
def recording() -> SimulatedSession:
    """Sesión breve con interacción, cámara y calibración."""
    screen = Screen("https://shop.local/", "Inicio", "/")
    button = Element("button", "go", "button", "Continuar", "#go", (100, 200, 120, 40))
    return (
        SessionBuilder(study_id=1, gaze_hz=4, face_hz=4)
        .with_calibration("initial", 1.5)
        .on_screen(screen)
        .with_rage_click(button)
        .build()
    )


@pytest.fixture
def recorded_data(connection: sqlite3.Connection, recording: SimulatedSession) -> SessionData:
    """Datos del constructor cargados por el repositorio real."""
    return store.load_session(connection, recording)


def test_removes_replayed_batches_sorts_streams_and_preserves_input(
    connection: sqlite3.Connection,
    recording: SimulatedSession,
    recorded_data: SessionData,
    params: Parameters,
) -> None:
    replayed = replace(
        recording,
        batches={
            name: records * 2 if name in STREAMS else records
            for name, records in recording.batches.items()
        },
    )
    loaded = store.load_session(connection, replayed)
    data = replace(loaded, **{name: getattr(loaded, name).iloc[::-1] for name in STREAMS})
    before = {name: getattr(data, name).copy(deep=True) for name in SESSION_FRAMES}

    cleaned = cleaning.clean(data, params)

    assert cleaned is not data
    assert cleaned.session is data.session
    for name in STREAMS:
        original = getattr(recorded_data, name)
        assert len(before[name]) == 2 * len(original) > 0
        expected = original.iloc[::-1].sort_values("t", kind="stable", ignore_index=True)
        assert_frame_equal(getattr(cleaned, name), expected, check_exact=True)
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(data, name), before[name], check_exact=True)
    validate_session_data(cleaned)


def test_keeps_distinct_events_at_the_same_time_and_preserves_tie_order(
    recorded_data: SessionData, params: Parameters
) -> None:
    base = recorded_data.events.query("type == 'click'").iloc[0].to_dict()
    base["data"] = {"items": [1, {"a": 2, "b": 3}]}
    late = {**base, "t": base["t"] + 100}
    other_element = {**base, "element": {**base["element"], "id": "other"}}
    other_data = {**base, "data": {"items": [1, {"a": 2, "b": 4}]}}
    other_task = {**base, "task_id": 1}
    duplicate = {
        **base,
        "element": dict(reversed(base["element"].items())),
        "data": {"items": [1, {"b": 3, "a": 2}]},
    }
    events = columns.frame("events", [late, base, other_element, other_data, other_task, duplicate])
    events.index = [8, 3, 4, 3, 9, 1]

    cleaned = cleaning.clean(replace(recorded_data, events=events), params)

    expected = columns.frame("events", [base, other_element, other_data, other_task, late])
    assert_frame_equal(cleaned.events, expected, check_exact=True)


@pytest.mark.parametrize(
    ("name", "invalid", "different"),
    [
        ("gaze", {"valid": False}, {"valid": False, "scroll_x": 100}),
        ("face", {"face_detected": False}, {"face_detected": False, "head_yaw": 1}),
    ],
)
def test_deduplicates_missing_camera_samples_without_losing_distinct_measurements(
    recorded_data: SessionData,
    params: Parameters,
    name: str,
    invalid: dict,
    different: dict,
) -> None:
    t = recorded_data.session.started_at + 100
    first = {"t": t, **invalid}
    second = {"t": t, **different}
    frame = columns.frame(name, [first, first, second])

    cleaned = cleaning.clean(replace(recorded_data, **{name: frame}), params)

    assert_frame_equal(
        getattr(cleaned, name), columns.frame(name, [first, second]), check_exact=True
    )


@pytest.mark.parametrize("delay_ms", [0.0, 37.5])
def test_applies_camera_delay_only_to_gaze_and_face(
    recorded_data: SessionData, params: Parameters, delay_ms: float
) -> None:
    before = {name: getattr(recorded_data, name).copy(deep=True) for name in SESSION_FRAMES}

    cleaned = cleaning.clean(recorded_data, replace(params, camera_delay_ms=delay_ms))

    for name in SESSION_FRAMES:
        expected = before[name].copy(deep=True)
        if name in ("gaze", "face"):
            expected["t"] = expected["t"] - delay_ms
        assert_frame_equal(getattr(cleaned, name), expected, check_exact=True)
        assert_frame_equal(getattr(recorded_data, name), before[name], check_exact=True)
    validate_session_data(cleaned)


def test_empty_streams_keep_their_columns_and_types(
    recorded_data: SessionData, params: Parameters
) -> None:
    data = replace(recorded_data, **{name: columns.empty(name) for name in STREAMS})

    cleaned = cleaning.clean(data, replace(params, camera_delay_ms=37.5))

    for name in STREAMS:
        assert_frame_equal(getattr(cleaned, name), columns.empty(name), check_exact=True)
    validate_session_data(cleaned)
