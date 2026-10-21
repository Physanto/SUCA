"""Pruebas del constructor de sesiones simuladas.

Cada patrón se comprueba contra los umbrales de ``parameters.yaml`` leídos en
la prueba: el constructor los supera por defecto y la verdad solo cuenta como
incidente lo que los supera.
"""

import dataclasses
import math
from typing import Any

import pytest

from analysis.parameters import Parameters
from scripts.simulation import scenarios
from scripts.simulation.builder import (
    BuilderError,
    Click,
    SessionBuilder,
    SimulatedSession,
    count_steps,
)
from shared import contracts


def builder(**options: Any) -> SessionBuilder:
    """Constructor de una sesión libre de prueba."""
    return SessionBuilder(study_id=1, **{"mode": "free", "seed": 1, **options})


def events(session: SimulatedSession, *types: str) -> list[dict[str, Any]]:
    """Eventos de una sesión, opcionalmente de algunos tipos."""
    return [item for item in session.batches["events"] if not types or item["type"] in types]


def incident_types(session: SimulatedSession) -> list[str]:
    """Tipos de los incidentes esperados, en orden."""
    return [item.type for item in session.truth.incidents]


def assert_valid(session: SimulatedSession) -> None:
    """Comprueba con los contratos cada lote, la petición de sesión y el SUS."""
    assert contracts.validate("new-session", session.request) == []
    for batch_type, records in session.batches.items():
        batch = {"contract_version": "1.0.0", "type": batch_type, "records": list(records)}
        assert contracts.validate("batch", batch) == [], batch_type
    if session.sus_answers is not None:
        assert contracts.validate("sus-answers", {"answers": list(session.sus_answers)}) == []


def test_the_same_seed_builds_the_same_session(shop: Any) -> None:
    def build(seed: int) -> SimulatedSession:
        return (
            builder(seed=seed).on_screen(shop.HOME).do(*shop.PATH).with_rage_click(shop.GO).build()
        )

    assert build(4) == build(4)
    assert build(4).batches["events"] != build(5).batches["events"]


def test_every_record_matches_its_contract_and_time_never_goes_back(shop: Any) -> None:
    session = (
        builder(mode="guided", reference_durations={1: 3000})
        .with_calibration("initial", 1.5)
        .on_screen(shop.HOME)
        .with_task(1, shop.PATH)
        .with_rage_click()
        .follow(1)
        .with_dead_click(shop.IMAGE)
        .with_navigation_loop(
            Click(shop.HOME_LINK, to=shop.HOME), Click(shop.CART_LINK, to=shop.CART)
        )
        .with_hesitation()
        .with_form_error(erases=True)
        .with_long_pause()
        .end_task("reference")
        .with_calibration("final", 1.8)
        .with_sus([4, 2, 4, 2, 4, 2, 4, 2, 4, 2])
        .build()
    )

    assert_valid(session)
    for records in session.batches.values():
        times = [item.get("t", item.get("t_start")) for item in records]
        assert times == sorted(times)
    assert session.started_at < session.batches["events"][0]["t"]
    assert session.batches["events"][-1]["t"] < session.ended_at


def test_rage_click_exceeds_the_thresholds_and_the_page_answers_in_time(
    shop: Any, params: Parameters
) -> None:
    session = builder().on_screen(shop.HOME).with_rage_click(shop.GO).build()

    clicks = events(session, "click")
    rage = params.rage_click
    assert len(clicks) >= rage.min_clicks
    assert clicks[-1]["t"] - clicks[0]["t"] <= rage.window_ms
    first = (clicks[0]["x"], clicks[0]["y"])
    assert all(math.dist(first, (item["x"], item["y"])) <= rage.radius_px for item in clicks)
    answered = {item["data"]["click_t"]: item["t"] for item in events(session, "click_response")}
    assert all(answered[item["t"]] - item["t"] <= params.dead_click.wait_ms for item in clicks)
    assert incident_types(session) == ["rage_click"]


def test_a_burst_below_the_minimum_is_not_an_incident(shop: Any, params: Parameters) -> None:
    clicks = params.rage_click.min_clicks - 1
    session = builder().on_screen(shop.HOME).with_rage_click(shop.GO, clicks=clicks).build()

    assert len(events(session, "click")) == clicks
    assert incident_types(session) == []


def test_patterns_follow_other_thresholds(shop: Any, params: Parameters) -> None:
    custom = dataclasses.replace(
        params, rage_click=dataclasses.replace(params.rage_click, min_clicks=6)
    )

    session = builder(params=custom).on_screen(shop.HOME).with_rage_click(shop.GO).build()

    assert len(events(session, "click")) == 7


def test_dead_click_gets_no_response_within_the_wait(shop: Any, params: Parameters) -> None:
    session = builder().on_screen(shop.HOME).with_dead_click(shop.IMAGE).do(shop.PATH[0]).build()

    click = events(session, "click")[0]
    later = [item for item in events(session) if item["t"] > click["t"]]
    assert later[0]["t"] - click["t"] > params.dead_click.wait_ms
    assert all(item.get("data", {}).get("click_t") != click["t"] for item in later)
    (incident,) = session.truth.incidents
    assert (incident.type, incident.t_start, incident.element["id"]) == (
        "dead_click",
        click["t"],
        "zoom",
    )


def test_long_pause_and_hesitation_are_gaps_of_the_right_size(
    shop: Any, params: Parameters
) -> None:
    session = (
        builder()
        .on_screen(shop.HOME)
        .do(shop.PATH[0])
        .with_long_pause()
        .with_hesitation(shop.HOME_LINK)
        .do(Click(shop.CART_LINK, to=shop.CART))
        .build()
    )

    pause, hesitation = session.truth.incidents
    times = [item["t"] for item in events(session)]
    assert (pause.type, hesitation.type) == ("long_pause", "hesitation")
    assert pause.t_start in times and pause.t_end in times
    assert not [t for t in times if pause.t_start < t < pause.t_end]
    assert pause.t_end - pause.t_start > params.long_pause_ms
    assert params.hesitation_ms < hesitation.t_end - hesitation.t_start < params.long_pause_ms


def test_short_pauses_are_not_incidents(shop: Any, params: Parameters) -> None:
    session = (
        builder()
        .on_screen(shop.HOME)
        .do(shop.PATH[0])
        .with_long_pause(params.long_pause_ms * 0.5)
        .with_hesitation(shop.HOME_LINK, ms=params.hesitation_ms * 0.5)
        .do(Click(shop.CART_LINK, to=shop.CART))
        .build()
    )

    assert incident_types(session) == []


def test_navigation_loop_goes_a_b_a(shop: Any) -> None:
    session = (
        builder()
        .on_screen(shop.HOME)
        .with_navigation_loop(
            Click(shop.HELP_LINK, to=shop.HELP), Click(shop.HOME_LINK, to=shop.HOME)
        )
        .build()
    )

    patterns = [scenarios_pattern(item) for item in events(session, "screen_change")]
    assert patterns == ["/", "/help", "/"]
    (loop,) = session.truth.incidents
    assert (loop.type, loop.screen) == ("navigation_loop", "/")


def scenarios_pattern(event: dict[str, Any]) -> str:
    """Pantalla normalizada de un evento de la tienda mínima."""
    return event["screen"]["url"].removeprefix("https://shop.local")


def test_task_results_count_steps_deviations_and_success(shop: Any) -> None:
    session = (
        builder(mode="guided")
        .on_screen(shop.HOME)
        .with_task(1, shop.PATH)
        .with_deviation_at_step(
            count_steps(shop.PATH[:1]),
            Click(shop.HELP_LINK, to=shop.HELP),
            back=Click(shop.CART_LINK, to=shop.CART),
        )
        .end_task("reference")
        .with_task(2, shop.PATH)
        .follow(1)
        .end_task("gave_up")
        .build()
    )

    completed, abandoned = session.truth.tasks
    assert completed.success and not abandoned.success
    assert completed.path_steps == count_steps(shop.PATH) == 6
    assert completed.steps == 6 + 4
    assert completed.deviation_step == 2
    assert completed.off_path_ms > 0
    assert abandoned.deviation_step is None
    assert [item["ended_by"] for item in session.batches["tasks"]] == ["reference", "gave_up"]


def test_form_error_produces_errors_and_reentries(shop: Any) -> None:
    session = (
        builder(mode="guided")
        .on_screen(shop.HOME)
        .with_task(1, shop.PATH)
        .follow(1)
        .with_form_error(times=2)
        .end_task("reference")
        .build()
    )

    assert incident_types(session) == ["form_error", "field_reentry"] * 2
    assert len(events(session, "validation_error")) == 2
    (task,) = session.truth.tasks
    assert task.success and task.deviation_step is None
    form = next(item for item in session.truth.episodes if item.type == "form")
    assert form.metrics == {"errors": 2, "reentries": 2}


def test_reference_mode_records_the_path(shop: Any) -> None:
    session = (
        builder(mode="reference")
        .on_screen(shop.HOME)
        .with_task(1, shop.PATH)
        .follow()
        .end_task("done")
        .build()
    )

    (recording,) = session.references
    assert len(recording.steps) == count_steps(shop.PATH)
    assert recording.required_steps == (4,)
    document = {
        "steps": list(recording.steps),
        "candidates": [],
        "end_condition": None,
        "required_steps": list(recording.required_steps),
    }
    assert contracts.validate("reference", document) == []
    assert "gaze" not in session.batches
    assert session.truth.tasks == ()


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda b, s: b.end_task(), "end_task\\(\\) needs a task"),
        (lambda b, s: b.with_task(1, s.PATH).build(), "task 1 is still open"),
        (lambda b, s: b.with_rage_click().build(), "waited for an action that never came"),
        (
            lambda b, s: b.with_task(1, s.PATH).with_deviation_at_step(3, Click(s.GO)),
            "not at the start",
        ),
        (
            lambda b, s: b.with_navigation_loop(
                Click(s.GO, to=s.CART), Click(s.HELP_LINK, to=s.HELP)
            ),
            "navigation loop needs",
        ),
        (lambda b, s: b.with_task(1, s.PATH).with_overtime(), "needs the reference duration"),
    ],
)
def test_reports_impossible_sessions(shop: Any, build: Any, message: str) -> None:
    with pytest.raises(BuilderError, match=message):
        build(builder().on_screen(shop.HOME), shop)


def test_normal_behavior_never_crosses_a_threshold(
    context: scenarios.StudyContext, params: Parameters
) -> None:
    """En V0 no hay huecos de vacilación, ni ráfagas, ni clics sin respuesta."""
    session = scenarios.guided_v0(context)

    times = [item["t"] for item in events(session)]
    assert max(b - a for a, b in zip(times, times[1:], strict=False)) < params.hesitation_ms
    clicks = events(session, "click")
    for index in range(len(clicks) - params.rage_click.min_clicks + 1):
        window = clicks[index : index + params.rage_click.min_clicks]
        assert window[-1]["t"] - window[0]["t"] > params.rage_click.window_ms
    answered = {item["data"]["click_t"] for item in events(session, "click_response")}
    focused = {item["t"] for item in events(session, "focus_in")}
    for click in clicks:
        responded = click["t"] in answered or any(0 < t - click["t"] < 100 for t in focused)
        assert responded, click
    assert session.truth.incidents == ()
