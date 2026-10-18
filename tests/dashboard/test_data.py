"""Pruebas del acceso a datos del panel (``dashboard/data.py``) sobre la base simulada.

Los valores esperados salen de la verdad de referencia de la base simulada.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dashboard.data import DashboardData, InvalidReferenceError, NotFoundError, open_data
from shared import db
from shared.config import ROOT_DIR

DASHBOARD = ROOT_DIR / "dashboard"


def test_lists_the_study_with_its_sessions(data: DashboardData) -> None:
    studies = data.get_studies()

    assert studies[["id", "name", "sessions"]].values.tolist() == [[1, "Tienda de ejemplo", 5]]


def test_lists_the_sessions_with_their_summary(data: DashboardData, mock: Any) -> None:
    sessions = data.get_sessions(study_id=1).set_index("session_id")

    assert len(sessions) == 5
    for truth in mock.truth["sessions"]:
        row = sessions.loc[truth["session_id"]]
        assert row["incidents"] == len(truth["incidents"])
        assert row["duration_ms"] == pytest.approx(truth["ended_at"] - truth["started_at"], abs=0.1)
        if truth["sus_score"] is None:
            assert np.isnan(row["sus_score"])
        else:
            assert row["sus_score"] == truth["sus_score"]
        if truth["usability_index"] is not None:
            assert row["bui"] == truth["usability_index"]["bui"]


@pytest.mark.parametrize(
    ("versions", "modes", "expected"),
    [
        (["V1"], None, [3, 5]),
        (None, ["guided"], [2, 3, 4]),
        (["V1"], ["free"], [5]),
        (["V9"], None, []),
    ],
)
def test_filters_sessions_by_version_and_mode(
    data: DashboardData, versions: Any, modes: Any, expected: list[int]
) -> None:
    sessions = data.get_sessions(study_id=1, versions=versions, modes=modes)

    assert sessions["session_id"].tolist() == expected


def test_gets_one_session(data: DashboardData) -> None:
    session = data.get_session(4)

    assert (session["participant_id"], session["version"], session["mode"]) == (
        "P03",
        "V2",
        "guided",
    )
    assert session["screen_info"]["window_width"] == 1280
    assert session["calibration_error_end"] == 2.6
    assert data.get_session(99) is None


def test_gets_events_with_their_screen_and_element(data: DashboardData) -> None:
    events = data.get_events(4)
    clicks = data.get_events(4, types=["click"])

    assert events["t"].is_monotonic_increasing
    assert set(clicks["type"]) == {"click"}
    assert all(isinstance(element, dict) for element in clicks["element"])
    assert events.loc[0, "url"] == "https://shop.local/login"
    assert str(events["task_id"].dtype) == "Int64"
    assert data.get_events(99).empty


def test_gets_the_tasks_of_a_session_with_their_results(data: DashboardData, mock: Any) -> None:
    tasks = data.get_session_tasks(mock.session("guided_v2")["session_id"])
    expected = {item["task_id"]: item for item in mock.session("guided_v2")["tasks"]}

    assert tasks["position"].tolist() == [1, 2, 3, 4]
    for row in tasks.itertuples():
        assert row.success == expected[row.task_id]["success"]
        assert row.ended_by == expected[row.task_id]["ended_by"]
    assert tasks.set_index("position").loc[3, "deviation_step"] == 8
    assert data.get_session_tasks(mock.session("free_v1")["session_id"]).empty


def test_gets_incidents_and_episodes_like_the_ground_truth(data: DashboardData, mock: Any) -> None:
    for truth in mock.truth["sessions"]:
        session_id = truth["session_id"]
        incidents = data.get_incidents(session_id=session_id)
        assert Counter(incidents["type"]) == Counter(item["type"] for item in truth["incidents"])
        episodes = data.get_episodes(session_id)
        assert len(episodes) == len(truth["episodes"])
        assert all(isinstance(metrics, dict) for metrics in episodes["metrics"])
    total = sum(len(item["incidents"]) for item in mock.truth["sessions"])
    assert len(data.get_incidents(study_id=1)) == total


def test_gets_face_and_gaze_samples(data: DashboardData) -> None:
    face = data.get_face(4)
    gaze = data.get_gaze(4)
    every = data.get_gaze(4, valid_only=False)

    assert len(face) > 0 and face["face_detected"].all()
    assert all(isinstance(values, dict) for values in face["values"])
    assert gaze["valid"].all()
    assert len(every) > len(gaze)


def test_gets_task_results_index_and_screens_of_the_study(data: DashboardData, mock: Any) -> None:
    guided = [item for item in mock.truth["sessions"] if item["mode"] == "guided"]
    results = data.get_task_results(1)
    index = data.get_usability_index(1)
    screens = data.get_screen_summary(1).set_index("screen")

    assert len(results) == sum(len(item["tasks"]) for item in guided) == 12
    assert set(results["version"]) == {"V0", "V1", "V2"}
    assert index["bui"].tolist() == [item["usability_index"]["bui"] for item in guided]
    assert index["sus_score"].tolist() == [item["sus_score"] for item in guided]
    expected = Counter(
        incident["screen"] for item in mock.truth["sessions"] for incident in item["incidents"]
    )
    assert {screen: count for screen, count in screens["incidents"].items() if count} == expected
    assert (screens["time_ms"] > 0).all()


def test_gets_the_references_and_captures(data: DashboardData) -> None:
    references = data.get_references(1)
    captures = data.get_screen_captures(1)

    assert references["status"].tolist() == ["confirmed"] * 4
    assert references.set_index("position").loc[3, "required_steps"] == [8, 13]
    assert all(isinstance(steps, list) and steps for steps in references["steps"])
    assert data.get_references(1, status="draft").empty
    assert captures.empty
    assert "absolute_path" in captures.columns


def test_capture_paths_are_relative_to_the_database_folder(
    writable: DashboardData, copy_path: Path
) -> None:
    with open_data(copy_path) as other:
        other._connection.execute(
            "INSERT INTO screen_capture (study_id, screen, file_path, t) VALUES (1, ?, ?, 1)",
            (json.dumps({"url": "https://shop.local/", "title": "Inicio"}), "captures/1/a.png"),
        )

    capture = writable.get_screen_captures(1).iloc[0]

    assert capture["url"] == "https://shop.local/"
    assert capture["absolute_path"] == str(copy_path.parent / "captures" / "1" / "a.png")


def test_accepts_ids_taken_from_a_dataframe(data: DashboardData) -> None:
    """Un id de un DataFrame es ``numpy.int64``; sin convertirlo, SQLite no encontraría nada."""
    study_id = data.get_studies()["id"].iloc[0]
    session_id = data.get_sessions()["session_id"].iloc[3]

    assert isinstance(study_id, np.integer)
    assert len(data.get_task_results(study_id)) == 12
    assert len(data.get_events(session_id)) > 0
    assert data.get_session(session_id)["id"] == 4


def test_reading_never_writes(data: DashboardData) -> None:
    connection = data._connection
    before = connection.total_changes

    data.get_studies()
    data.get_sessions()
    for session_id in range(1, 6):
        data.get_session(session_id)
        data.get_events(session_id)
        data.get_session_tasks(session_id)
        data.get_incidents(session_id=session_id)
        data.get_episodes(session_id)
        data.get_face(session_id)
        data.get_gaze(session_id)
    for method in ("get_task_results", "get_screen_summary", "get_usability_index",
                   "get_references", "get_screen_captures"):  # fmt: skip
        getattr(data, method)(1)

    assert connection.total_changes == before


# --- La única escritura: confirmar una referencia ------------------------------------


def make_draft(path: Path, reference_id: int) -> None:
    """Deja una referencia de la copia en borrador, como la dejaría el panel lateral."""
    with open_data(path) as other, db.transaction(other._connection):
        other._connection.execute(
            "UPDATE reference SET status = 'draft', end_condition = NULL, required_steps = '[]'"
            " WHERE id = ?",
            (reference_id,),
        )


def test_confirms_the_end_condition_and_required_steps(
    writable: DashboardData, copy_path: Path
) -> None:
    make_draft(copy_path, 1)
    condition = {"type": "visible_text", "text": "Audífonos inalámbricos SoundMax"}

    writable.confirm_reference(1, condition, [0, 3])

    reference = writable.get_references(1).set_index("reference_id").loc[1]
    assert reference["status"] == "confirmed"
    assert reference["end_condition"] == condition
    assert reference["required_steps"] == [0, 3]


@pytest.mark.parametrize(
    ("condition", "required", "message"),
    [
        ({"type": "visible_text"}, [0], "text"),
        ({"type": "nearby", "text": "x"}, [0], "nearby"),
        ({"type": "url_pattern", "pattern": "/product/{id}"}, [0, 0], "non-unique|unique"),
        ({"type": "url_pattern", "pattern": "/product/{id}"}, [99], "required steps \\[99\\]"),
    ],
)
def test_rejects_invalid_confirmations_and_changes_nothing(
    writable: DashboardData, copy_path: Path, condition: Any, required: list[int], message: str
) -> None:
    make_draft(copy_path, 1)

    with pytest.raises(InvalidReferenceError, match=message):
        writable.confirm_reference(1, condition, required)

    reference = writable.get_references(1).set_index("reference_id").loc[1]
    assert (reference["status"], reference["end_condition"]) == ("draft", None)


def test_confirming_an_unknown_reference_fails(writable: DashboardData) -> None:
    with pytest.raises(NotFoundError, match="reference 99 not found"):
        writable.confirm_reference(99, {"type": "url_pattern", "pattern": "/x"}, [])


# --- Reglas del panel ------------------------------------------------------------------


def test_the_data_layer_does_not_import_streamlit() -> None:
    code = "import sys, dashboard.data; sys.exit('streamlit' in sys.modules)"

    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_pages_and_navigation_have_no_sql() -> None:
    files = [DASHBOARD / "app.py", DASHBOARD / "ui.py", *sorted((DASHBOARD / "pages").glob("*.py"))]

    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "SELECT " not in source and ".execute(" not in source, path.name
