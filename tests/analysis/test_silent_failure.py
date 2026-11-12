"""Fallo silencioso: un envío que falla sin un aviso que la captura reconozca."""

import sqlite3
from dataclasses import replace
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import cleaning, columns, detectors, episodes, screens
from analysis.loader import SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters, SilentFailureParams
from scripts.simulation import scenarios, store
from scripts.simulation.builder import BuilderError, FillForm, SessionBuilder

FORM = scenarios.SHIP_FORM.descriptor()
NAME = scenarios.SHIP_NAME.descriptor()
ADDRESS = scenarios.SHIP_ADDRESS.descriptor()


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Sesión base para eventos con límites controlados."""
    return repository.load_session(1)


def capture(data: SessionData, records: list[dict[str, Any]]) -> SessionData:
    """Eventos de un formulario con tiempos relativos al inicio de la sesión."""
    return replace(
        data,
        events=columns.frame(
            "events",
            [
                {
                    "type": "field_change",
                    "url": "https://shop.local/checkout/shipping",
                    "title": "Envío",
                    "screen": "/checkout/shipping",
                    "element": NAME,
                    **item,
                    "t": data.session.started_at + item["t"],
                }
                for item in records
            ],
        ),
    )


def submit(t: float) -> dict[str, Any]:
    """Un ``form_submit`` del formulario de envío."""
    return {"t": t, "type": "form_submit", "element": FORM}


def found(data: SessionData, params: Parameters, records: list[dict[str, Any]]) -> list[float]:
    """Tiempos (relativos) de los fallos silenciosos que detecta."""
    result = detectors.SilentFailureDetector().find(capture(data, records), params)
    return [t - data.session.started_at for t in result["t"]]


def test_correcting_a_filled_field_after_a_submit_without_error_is_a_silent_failure(
    data: SessionData, params: Parameters
) -> None:
    assert found(data, params, [{"t": 0}, submit(100), {"t": 3000}]) == [100]


def test_a_recognized_validation_error_is_not_a_silent_failure(
    data: SessionData, params: Parameters
) -> None:
    error = {"t": 150, "type": "validation_error", "data": {"error_type": "aria_invalid"}}
    assert found(data, params, [{"t": 0}, submit(100), error, {"t": 3000}]) == []


def test_editing_a_new_field_after_a_submit_is_not_a_retry(
    data: SessionData, params: Parameters
) -> None:
    """Un formulario de varios pasos en la misma pantalla no es un fallo."""
    assert found(data, params, [{"t": 0}, submit(100), {"t": 3000, "element": ADDRESS}]) == []


def test_leaving_the_screen_after_the_submit_is_progress(
    data: SessionData, params: Parameters
) -> None:
    moved = {
        "t": 200,
        "type": "screen_change",
        "url": "https://shop.local/checkout/payment",
        "screen": "/checkout/payment",
        "element": None,
    }
    # La edición posterior ocurre en otra pantalla: es otro formulario.
    again = {"t": 3000, "url": moved["url"], "screen": moved["screen"]}
    assert found(data, params, [{"t": 0}, submit(100), moved, again]) == []


def test_the_retry_window_decides_what_is_still_a_retry(
    data: SessionData, params: Parameters
) -> None:
    window = params.silent_failure.retry_window_ms
    inside = [{"t": 0}, submit(100), {"t": 100 + window}]
    outside = [{"t": 0}, submit(100), {"t": 101 + window}]
    assert found(data, params, inside) == [100]
    assert found(data, params, outside) == []
    narrow = replace(params, silent_failure=SilentFailureParams(retry_window_ms=1000))
    assert found(data, narrow, [{"t": 0}, submit(100), {"t": 3000}]) == []


def test_each_failed_attempt_is_reported(data: SessionData, params: Parameters) -> None:
    records = [{"t": 0}, submit(100), {"t": 3000}, submit(4000), {"t": 7000}, submit(8000)]
    assert found(data, params, records) == [100, 4000]


def test_a_submit_without_any_retry_is_not_reported(data: SessionData, params: Parameters) -> None:
    assert found(data, params, [{"t": 0}, submit(100)]) == []


@pytest.mark.parametrize("times", [1, 2])
def test_builder_pattern_matches_its_truth_and_episodes(
    connection: sqlite3.Connection, params: Parameters, times: int
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.LOGIN)
        .with_silent_failure(1, times=times)
        .do(scenarios.LOGIN_ACTION)
        .build()
    )
    loaded = screens.assign_screens(
        cleaning.clean(store.load_session(connection, recording), params), params
    )

    incidents = detectors.detect(loaded, params)

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
        ],
    )
    assert len(truth) == times
    assert_frame_equal(incidents, truth, check_exact=False, rtol=0, atol=0.1)
    # El inicio de sesión repetido no da acceso hasta el último intento.
    logins = episodes.detect(loaded, params)
    logins = logins[logins["type"] == "login"]
    assert logins["outcome"].tolist() == ["failed"] * times + ["success"]
    assert logins["outcome"].tolist() == [
        item.outcome for item in recording.truth.episodes if item.type == "login"
    ]


def test_a_recognized_error_pattern_does_not_look_like_a_silent_failure(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.SHIPPING)
        .with_form_error(0, times=2, erases=True)
        .do(
            FillForm(
                scenarios.SHIP_FORM,
                (scenarios.SHIP_NAME, scenarios.SHIP_ADDRESS),
                scenarios.SHIP_SUBMIT,
                to=scenarios.PAYMENT,
            )
        )
        .build()
    )
    loaded = screens.assign_screens(
        cleaning.clean(store.load_session(connection, recording), params), params
    )

    assert detectors.SilentFailureDetector().find(loaded, params).empty


def test_repeated_searches_are_not_silent_failures(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    """Reformular una búsqueda es ``repeated_search``, no un envío fallido."""
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.HOME)
        .with_repeated_search(
            scenarios.SEARCH, [scenarios.results("uno"), scenarios.results("dos")]
        )
        .build()
    )
    loaded = screens.assign_screens(
        cleaning.clean(store.load_session(connection, recording), params), params
    )

    assert detectors.SilentFailureDetector().find(loaded, params).empty
    assert not detectors.DETECTORS.get("repeated_search").find(loaded, params).empty


def test_a_normal_login_is_a_success_and_not_a_silent_failure(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(scenarios.LOGIN)
        .do(scenarios.LOGIN_ACTION)
        .build()
    )
    loaded = screens.assign_screens(
        cleaning.clean(store.load_session(connection, recording), params), params
    )

    assert detectors.SilentFailureDetector().find(loaded, params).empty
    logins = episodes.detect(loaded, params)
    assert logins[logins["type"] == "login"]["outcome"].tolist() == ["success"]


def test_the_builder_refuses_incompatible_or_out_of_range_patterns() -> None:
    builder = SessionBuilder(study_id=1, camera=False).on_screen(scenarios.LOGIN)
    with pytest.raises(BuilderError, match="cannot share"):
        builder.with_form_error().with_silent_failure().do(scenarios.LOGIN_ACTION)
    other = SessionBuilder(study_id=1, camera=False).on_screen(scenarios.LOGIN)
    with pytest.raises(BuilderError, match="no field 5"):
        other.with_silent_failure(5).do(scenarios.LOGIN_ACTION)
    waiting = SessionBuilder(study_id=1, camera=False).on_screen(scenarios.LOGIN)
    with pytest.raises(BuilderError, match="waited for an action"):
        waiting.with_silent_failure().build()
