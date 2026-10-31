"""Alineación de rutas, repeticiones, obligaciones y evidencia del final de tarea."""

from dataclasses import replace
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from analysis import columns, reference
from analysis.loader import SESSION_FRAMES, SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from scripts.simulation import scenarios

A = scenarios.ADD_TO_CART.descriptor()
B = scenarios.CHECKOUT.descriptor()
C = scenarios.SHIP_SUBMIT.descriptor()
X = scenarios.MENU_HELP.descriptor()


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Tarea guiada de un segundo; cada caso aporta su ruta y sus eventos."""
    loaded = repository.load_session(1)
    start = loaded.session.started_at
    return replace(
        loaded,
        tasks=columns.frame(
            "tasks", [{"task_id": 1, "t_start": start, "t_end": start + 1000, "ended_by": "done"}]
        ),
    )


def events(data: SessionData, records: list[dict]) -> pd.DataFrame:
    """Eventos con tiempo relativo, en una pantalla conocida y con elementos reales."""
    return columns.frame(
        "events",
        [
            {
                "type": "click",
                "url": "https://shop.local/flow",
                "title": "Flujo",
                "screen": "/flow",
                "task_id": 1,
                "element": A,
                **row,
                "t": data.session.started_at + row["t"],
            }
            for row in records
        ],
    )


def with_route(
    data: SessionData,
    path: list[dict],
    actual: list[dict],
    *,
    required: list[int] | None = None,
    condition: dict | None = None,
) -> SessionData:
    """Construye una referencia del contrato sin invocar la extracción del análisis."""
    steps = [
        {
            "t": row.t,
            "type": row.type,
            "screen": {"url": row.url, "title": row.title},
            "element": None if row.type == "screen_change" else row.element,
        }
        for row in events(data, path).itertuples()
    ]
    return replace(
        data,
        events=events(data, actual),
        references=columns.frame(
            "references",
            [
                {
                    "id": 1,
                    "task_id": 1,
                    "steps": steps,
                    "duration_ms": 1000,
                    "required_steps": list(range(len(steps))) if required is None else required,
                    "end_condition": condition or {"type": "url_pattern", "pattern": "/flow"},
                }
            ],
        ),
    )


def result(data: SessionData, params: Parameters) -> Any:
    """Devuelve y valida el único resultado de la tarea del caso."""
    found = reference.compare(data, params)
    columns.validate(found, "task_result")
    assert len(found) == 1
    return found.iloc[0]


def test_correct_route_and_repeated_steps_preserve_inputs(
    data: SessionData, params: Parameters
) -> None:
    path = [{"t": 100}, {"t": 200, "element": B}, {"t": 400, "element": C}]
    loaded = with_route(
        data,
        path,
        [
            {"t": 100},
            {"t": 150},
            {"t": 200, "element": B},
            {"t": 300},
            {"t": 400, "element": C},
        ],
    )
    before = {name: getattr(loaded, name).copy(deep=True) for name in SESSION_FRAMES}
    row = result(loaded, params)
    assert row["success"] and row["steps"] == 5 and row["duration_ms"] == 1000
    assert pd.isna(row["deviation_step"]) and row["off_path_ms"] == 0
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(loaded, name), before[name], check_exact=True)


@pytest.mark.parametrize(
    ("actual", "off_path", "success"),
    [
        (
            [
                {"t": 100},
                {"t": 200, "element": X},
                {"t": 300, "element": X},
                {"t": 500, "element": B},
                {"t": 700, "element": C},
            ],
            300,
            True,
        ),
        ([{"t": 100}, {"t": 200, "element": X}], 800, False),
        (
            [
                {"t": 100},
                {"t": 200, "element": X},
                {"t": 400, "element": B},
                {"t": 600, "element": X},
                {"t": 900, "element": C},
            ],
            500,
            True,
        ),
    ],
)
def test_counts_excursions_from_the_first_bad_step_until_return_or_task_end(
    data: SessionData, params: Parameters, actual: list[dict], off_path: float, success: bool
) -> None:
    loaded = with_route(
        data, [{"t": 100}, {"t": 400, "element": B}, {"t": 900, "element": C}], actual
    )
    row = result(loaded, params)
    assert bool(row["success"]) is success
    assert row["steps"] == len(actual) and row["deviation_step"] == 1
    assert row["off_path_ms"] == off_path


@pytest.mark.parametrize(("required", "success"), [([0, 2], True), ([0, 1, 2], False)])
def test_skipping_a_step_is_a_deviation_and_cannot_satisfy_a_missing_obligation(
    data: SessionData, params: Parameters, required: list[int], success: bool
) -> None:
    loaded = with_route(
        data,
        [{"t": 100}, {"t": 200, "element": B}, {"t": 400, "element": C}],
        [{"t": 100}, {"t": 400, "element": C}],
        required=required,
    )
    row = result(loaded, params)
    assert bool(row["success"]) is success
    assert row["deviation_step"] == 1 and row["off_path_ms"] == 600


def test_text_and_role_survive_changed_ids_selectors_and_geometry(
    data: SessionData, params: Parameters
) -> None:
    changed = {
        **A,
        "id": "new-id",
        "selector": "#new-id",
        "box": {"x": 0, "y": 0, "w": 4, "h": 4},
        "text": "  Agregar   al carrito ",
    }
    row = result(with_route(data, [{"t": 100}], [{"t": 200, "element": changed}]), params)
    assert row["success"] and pd.isna(row["deviation_step"])


@pytest.mark.parametrize("change", ["role", "screen", "type", "title"])
def test_different_roles_screens_step_types_and_ambiguous_titles_do_not_match(
    data: SessionData, params: Parameters, change: str
) -> None:
    actual = {"t": 100}
    if change == "role":
        actual["element"] = {**A, "role": "link"}
    elif change == "screen":
        actual["url"] = "https://shop.local/other"
    elif change == "type":
        actual["type"] = "form_submit"
    else:
        actual["title"] = "Otra pantalla en la misma URL"
    row = result(with_route(data, [{"t": 100}], [actual]), params)
    assert not row["success"] and row["deviation_step"] == 0 and row["off_path_ms"] == 900


def test_normalized_ids_queries_and_spa_routes_match(data: SessionData, params: Parameters) -> None:
    loaded = with_route(
        data,
        [{"t": 100, "url": "https://old.local/#!/product/101?q=one"}],
        [{"t": 200, "url": "https://new.local/#/product/202?q=two"}],
        condition={"type": "url_pattern", "pattern": "/product/{id}"},
    )
    assert result(loaded, params)["success"]


@pytest.mark.parametrize("include_required", [True, False])
def test_blank_text_fields_use_their_captured_identity_to_check_obligations(
    data: SessionData, params: Parameters, include_required: bool
) -> None:
    actual = [{"t": 100, "element": scenarios.PAY_TRANSFER.descriptor()}]
    if include_required:
        actual.append({"t": 300, "element": scenarios.PAY_CARD.descriptor()})
    actual.append({"t": 500, "element": C})
    loaded = with_route(
        data,
        [{"t": 100, "element": scenarios.PAY_CARD.descriptor()}, {"t": 500, "element": C}],
        actual,
    )
    loaded.tasks["ended_by"] = "reference"
    row = result(loaded, params)
    assert bool(row["success"]) is include_required
    assert row["deviation_step"] == 0


def test_repeating_a_persistent_control_on_a_new_screen_keeps_the_route(
    data: SessionData, params: Parameters
) -> None:
    path = [
        {"t": 100},
        {"t": 200, "type": "screen_change", "url": "https://shop.local/search"},
        {"t": 500, "element": B, "url": "https://shop.local/search"},
    ]
    loaded = with_route(
        data,
        path,
        [*path[:2], {"t": 300, "url": "https://shop.local/search"}, path[2]],
        condition={"type": "url_pattern", "pattern": "/search"},
    )
    row = result(loaded, params)
    assert row["success"] and row["steps"] == 4
    assert pd.isna(row["deviation_step"]) and row["off_path_ms"] == 0


def test_returning_to_an_already_visited_route_screen_ends_the_excursion(
    data: SessionData, params: Parameters
) -> None:
    loaded = with_route(
        data,
        [{"t": 100}, {"t": 900, "element": B}],
        [
            {"t": 100},
            {"t": 200, "element": X},
            {"t": 300, "type": "screen_change", "url": "https://shop.local/help"},
            {"t": 700, "type": "screen_change"},
            {"t": 900, "element": B},
        ],
    )
    row = result(loaded, params)
    assert row["success"] and row["deviation_step"] == 1 and row["off_path_ms"] == 500


def test_accepts_alternative_references_independently_of_their_order(
    data: SessionData, params: Parameters
) -> None:
    first = with_route(data, [{"t": 100}, {"t": 400, "element": B}], [])
    second = with_route(
        data, [{"t": 100}, {"t": 400, "element": C}], [{"t": 100}, {"t": 400, "element": C}]
    )
    second.references.loc[0, "id"] = 2
    loaded = replace(
        second, references=pd.concat([first.references, second.references], ignore_index=True)
    )
    row = result(loaded, params)
    assert row["success"] and pd.isna(row["deviation_step"])
    assert_frame_equal(
        reference.compare(loaded, params),
        reference.compare(replace(loaded, references=loaded.references.iloc[::-1]), params),
    )


def test_obligations_from_different_references_cannot_be_combined(
    data: SessionData, params: Parameters
) -> None:
    first = with_route(data, [{"t": 100}, {"t": 400, "element": B}], [])
    second = with_route(
        data,
        [{"t": 100, "element": X}, {"t": 400, "element": C}],
        [{"t": 100}, {"t": 400, "element": C}],
    )
    second.references.loc[0, "id"] = 2
    loaded = replace(
        second, references=pd.concat([first.references, second.references], ignore_index=True)
    )
    loaded.tasks["ended_by"] = "reference"
    assert not result(loaded, params)["success"]


@pytest.mark.parametrize(
    ("kind", "ended_by", "observed", "success"),
    [
        ("visible_text", "done", True, True),
        ("element_present", "done", True, True),
        ("element_present", "done", False, False),
        ("visible_text", "done", False, False),
        ("visible_text", "reference", False, True),
    ],
)
def test_final_condition_requires_observed_evidence_or_automatic_completion(
    data: SessionData, params: Parameters, kind: str, ended_by: str, observed: bool, success: bool
) -> None:
    condition = {"type": kind, "text": "Pedido confirmado"}
    if kind == "element_present":
        condition["role"] = "status"
    actual = [{"t": 100}]
    if observed:
        actual.append(
            {
                "t": 500,
                "element": {
                    **A,
                    "text": "Pedido confirmado",
                    "role": "status",
                    "interactive": False,
                },
            }
        )
    loaded = with_route(data, [{"t": 100}], actual, condition=condition)
    loaded.tasks["ended_by"] = ended_by
    assert bool(result(loaded, params)["success"]) is success


def test_automatic_completion_cannot_replace_a_missing_required_step_or_the_final_screen(
    data: SessionData, params: Parameters
) -> None:
    loaded = with_route(
        data,
        [{"t": 100}, {"t": 500, "element": B}],
        [{"t": 100}],
        condition={"type": "visible_text", "text": "Listo"},
    )
    loaded.tasks["ended_by"] = "reference"
    assert not result(loaded, params)["success"]
    loaded = replace(
        loaded,
        events=events(
            data,
            [
                {"t": 100},
                {"t": 500, "element": B},
                {"t": 600, "type": "screen_change", "url": "https://shop.local/other"},
            ],
        ),
    )
    assert not result(loaded, params)["success"]


@pytest.mark.parametrize(
    "case", ["no_references", "empty_route", "missing_condition", "invalid_required"]
)
def test_missing_or_unusable_references_leave_alignment_unknown_but_keep_measurements(
    data: SessionData, params: Parameters, case: str
) -> None:
    loaded = with_route(data, [{"t": 100}], [{"t": 100}])
    if case == "no_references":
        loaded = replace(loaded, references=columns.empty("references"))
    elif case == "empty_route":
        loaded.references.at[0, "steps"] = []
    elif case == "missing_condition":
        loaded.references.at[0, "end_condition"] = None
    else:
        loaded.references.at[0, "required_steps"] = [99]
    row = result(loaded, params)
    assert not row["success"] and row["steps"] == 1 and row["duration_ms"] == 1000
    assert pd.isna(row["deviation_step"]) and pd.isna(row["off_path_ms"])


def test_only_counts_assigned_events_inside_the_task_and_ignores_camera_gaps(
    data: SessionData, params: Parameters
) -> None:
    loaded = with_route(
        data,
        [{"t": 100}],
        [
            {"t": -1},
            {"t": 100},
            {"t": 500, "task_id": 2},
            {"t": 600, "task_id": None},
            {"t": 1001},
            {"t": 800, "type": "camera_gap", "url": "https://shop.local/other"},
        ],
    )
    row = result(loaded, params)
    assert row["success"] and row["steps"] == 1 and row["off_path_ms"] == 0
    loaded = replace(loaded, events=columns.empty("events"))
    row = result(loaded, params)
    assert not row["success"] and row["steps"] == 0 and row["off_path_ms"] == 0


@pytest.mark.parametrize("mode", ["free", "reference"])
def test_unguided_sessions_do_not_have_task_results(
    data: SessionData, params: Parameters, mode: str
) -> None:
    data = replace(data, session=replace(data.session, mode=mode))
    assert_frame_equal(reference.compare(data, params), columns.empty("task_result"))


def test_invalid_task_intervals_are_reported(data: SessionData, params: Parameters) -> None:
    data.tasks.loc[0, "t_end"] = data.tasks.iloc[0]["t_start"] - 1
    with pytest.raises(ValueError, match="task 1: invalid time interval"):
        reference.compare(data, params)
