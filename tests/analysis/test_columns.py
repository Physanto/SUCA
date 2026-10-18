"""Pruebas de las columnas de las tablas del análisis y su validación."""

import re

import pandas as pd
import pytest

from analysis import columns
from analysis.columns import ColumnValidationError

INCIDENT = {"type": "rage_click", "t": 1000.0, "screen": "/cart", "task_id": 3, "element": None}


@pytest.mark.parametrize("table", sorted(columns.SPECS))
def test_empty_frames_have_the_columns_in_order_and_are_valid(table: str) -> None:
    df = columns.empty(table)

    assert list(df.columns) == list(columns.spec(table).columns)
    assert len(df) == 0
    columns.validate(df, table)


def test_frame_builds_typed_columns_and_allows_omitting_empty_values() -> None:
    df = columns.frame(
        "task_result", [{"task_id": 1, "success": True, "duration_ms": 10, "steps": 3}]
    )

    assert str(df["task_id"].dtype) == "Int64"
    assert df["success"].dtype == bool
    assert df["duration_ms"].dtype == "float64"
    assert df["deviation_step"].isna().all()
    columns.validate(df, "task_result")


def test_frame_rejects_unknown_columns_and_missing_required_values() -> None:
    with pytest.raises(ColumnValidationError, match=r"unknown columns \['severity'\]"):
        columns.frame("incident", [{**INCIDENT, "severity": 3}])
    with pytest.raises(ColumnValidationError, match="column 't' is required"):
        columns.frame("incident", [{"type": "rage_click"}])


def test_accepts_a_frame_built_with_plain_pandas() -> None:
    df = pd.DataFrame(
        {
            "type": ["rage_click"],
            "t": [1000.0],
            "screen": ["/cart"],
            "task_id": pd.array([None], dtype="Int64"),
            "element": [{"tag": "button"}],
        }
    )

    columns.validate(df, "incident")


def test_rejects_something_that_is_not_a_dataframe() -> None:
    with pytest.raises(ColumnValidationError, match="expected a DataFrame, got list"):
        columns.validate([], "incident")


def test_reports_missing_and_unexpected_columns_with_the_table() -> None:
    df = pd.DataFrame({"type": ["rage_click"], "t": [1.0], "severity": [3]})

    with pytest.raises(ColumnValidationError) as raised:
        columns.validate(df, "incident", label="detector rage_click")

    message = str(raised.value)
    assert message.startswith("detector rage_click: ")
    assert "missing columns ['screen', 'task_id', 'element']" in message
    assert "unexpected columns ['severity']" in message
    assert raised.value.table == "incident"


@pytest.mark.parametrize(
    ("column", "values", "message"),
    [
        ("t", ["late"], "column 't' must be float"),
        ("task_id", [3.0], "column 'task_id' must be int, got float64 (use Int64"),
        ("element", ["#pay"], "column 'element' must be json"),
        ("screen", [7], "column 'screen' must be text"),
        ("t", [None], "column 't' has empty values"),
        ("type", ["rageclick"], "column 'type' has values not in incident_type: ['rageclick']"),
    ],
)
def test_rejects_wrong_types_empty_values_and_unknown_types(
    column: str, values: list, message: str
) -> None:
    df = columns.frame("incident", [INCIDENT])
    df[column] = pd.Series(values, dtype="object" if values[0] is None else None)

    with pytest.raises(ColumnValidationError, match=re.escape(message)):
        columns.validate(df, "incident")


def test_rejects_repeated_tasks_and_more_than_one_index_row() -> None:
    result = {"task_id": 1, "success": False, "duration_ms": 1.0, "steps": 1}
    index = {"effectiveness": 1.0, "time_efficiency": 1.0, "path_efficiency": 1.0}
    index |= {"friction": 1.0, "bui": 1.0}

    with pytest.raises(ColumnValidationError, match=r"repeated values in \['task_id'\]"):
        columns.validate(columns.frame("task_result", [result, result]), "task_result")
    with pytest.raises(ColumnValidationError, match=r"at most 1 row\(s\), got 2"):
        columns.validate(columns.frame("usability_index", [index, index]), "usability_index")


def test_session_frames_allow_extra_columns() -> None:
    events = columns.empty("events").assign(is_duplicate=pd.Series(dtype=bool))

    columns.validate(events, "events")


def test_types_are_not_checked_in_a_frame_without_rows() -> None:
    df = pd.DataFrame(columns=list(columns.spec("incident").columns))

    columns.validate(df, "incident")


def test_concat_ignores_empty_frames_and_keeps_the_column_order() -> None:
    first = columns.frame("incident", [INCIDENT])
    second = columns.frame("incident", [{**INCIDENT, "type": "dead_click", "t": 500.0}])

    joined = columns.concat("incident", [columns.empty("incident"), first, second])

    assert list(joined["type"]) == ["rage_click", "dead_click"]
    assert list(joined.columns) == list(columns.spec("incident").columns)
    assert len(columns.concat("incident", [])) == 0
    columns.validate(joined, "incident")
