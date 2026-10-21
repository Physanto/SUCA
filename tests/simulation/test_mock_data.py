"""Pruebas de la base simulada y de su verdad de referencia.

Comprueban que el generador es determinista, que cada registro cumple su
contrato, que la verdad de referencia es coherente con los eventos guardados y
con las tablas de resultados, y que el pipeline corre sobre la base.
"""

import json
import math
import shutil
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import analyze_session
from scripts.generate_mock_data import generate, ground_truth_path, main
from scripts.simulation import scenarios
from shared import contracts, db
from shared.config import load_config

TABLES = (
    "participant",
    "session",
    "event",
    "gaze_sample",
    "face_sample",
    "calibration",
    "session_task",
    "sus_response",
    "reference",
    "episode",
    "incident",
    "task_result",
    "usability_index",
)


def dump(path: Path) -> dict[str, list[tuple]]:
    """Todas las filas de las tablas de datos, en orden."""
    with closing(db.open_database(path)) as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in TABLES
        }


def rows(connection: sqlite3.Connection, sql: str, *params: Any) -> list[dict[str, Any]]:
    """Filas de una consulta como diccionarios."""
    return [dict(row) for row in connection.execute(sql, params)]


def events(connection: sqlite3.Connection, session_id: int) -> list[dict[str, Any]]:
    """Eventos de una sesión, en orden, con sus JSON convertidos."""
    loaded = []
    for row in rows(
        connection, "SELECT * FROM event WHERE session_id = ? ORDER BY t, id", session_id
    ):
        row["data"] = json.loads(row["data"]) if row["data"] else None
        row["element"] = json.loads(row["element"]) if row["element"] else None
        loaded.append(row)
    return loaded


def incidents_of(mock: Any, kind: str) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    """Pares (sesión, incidente) de un tipo en toda la verdad de referencia."""
    for session in mock.truth["sessions"]:
        for incident in session["incidents"]:
            if incident["type"] == kind:
                yield session, incident


# --- Determinismo y contratos --------------------------------------------------


def test_the_generator_is_deterministic(mock: Any, tmp_path: Path) -> None:
    again = tmp_path / "again.db"
    generate(again)

    assert dump(again) == dump(mock.path)
    assert ground_truth_path(again).read_bytes() == ground_truth_path(mock.path).read_bytes()


def test_the_ground_truth_uses_unix_line_endings(mock: Any) -> None:
    """Así el archivo es idéntico en Windows, macOS y Linux."""
    assert b"\r\n" not in ground_truth_path(mock.path).read_bytes()


def test_every_record_matches_its_contract(context: scenarios.StudyContext) -> None:
    sessions = [scenarios.reference_recording(context)]
    sessions += [scenario(context) for _, scenario in scenarios.PARTICIPANT_SCENARIOS]

    for session in sessions:
        assert contracts.validate("new-session", session.request) == []
        for batch_type, records in session.batches.items():
            batch = {
                "contract_version": contracts.contract_version(),
                "type": batch_type,
                "records": list(records),
            }
            assert contracts.validate("batch", batch) == [], (session.request, batch_type)
        if session.sus_answers is not None:
            assert contracts.validate("sus-answers", {"answers": list(session.sus_answers)}) == []


def test_references_are_confirmed_and_match_their_contract(
    mock_connection: sqlite3.Connection,
) -> None:
    references = rows(mock_connection, "SELECT * FROM reference ORDER BY task_id")

    assert [(item["task_id"], item["status"]) for item in references] == [
        (1, "confirmed"),
        (2, "confirmed"),
        (3, "confirmed"),
        (4, "confirmed"),
    ]
    for item in references:
        document = {
            key: json.loads(item[key])
            for key in ("steps", "candidates", "end_condition", "required_steps")
        }
        assert contracts.validate("reference", document) == []
        assert item["duration_ms"] > 0


# --- Lo que pide el plan ---------------------------------------------------------


def test_the_mock_has_the_planned_sessions(mock: Any, mock_connection: sqlite3.Connection) -> None:
    sessions = rows(mock_connection, "SELECT id, version, mode, ended_at FROM session ORDER BY id")

    assert [(item["version"], item["mode"]) for item in sessions] == [
        ("V0", "reference"),
        ("V0", "guided"),
        ("V1", "guided"),
        ("V2", "guided"),
        ("V1", "free"),
    ]
    assert all(item["ended_at"] is not None for item in sessions)
    counts = {
        table: mock_connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("gaze_sample", "face_sample", "calibration", "sus_response")
    }
    assert all(counts.values()), counts
    assert len(mock.truth["study"]["tasks"]) == 4


def test_seeded_problems_follow_the_versions(mock: Any) -> None:
    def problems(key: str) -> set[int]:
        return {item["problem"] for item in mock.session(key)["incidents"] if item["problem"]}

    assert mock.session("guided_v0")["incidents"] == []
    assert problems("guided_v1") == {1, 2, 3, 4}
    assert problems("guided_v2") == set(range(1, 9))
    assert {int(number) for number in mock.truth["seeded_problems"]} == set(range(1, 9))


def test_every_incident_type_appears_somewhere(mock: Any) -> None:
    found = {item["type"] for session in mock.truth["sessions"] for item in session["incidents"]}

    assert found == set(contracts.enums()["incident_type"])


def test_the_deviation_happens_at_the_known_step(mock: Any) -> None:
    tasks = {item["task_id"]: item for item in mock.session("guided_v2")["tasks"]}
    card_step = next(item for item in mock.truth["references"] if item["task_id"] == 3)

    assert tasks[3]["deviation_step"] == card_step["required_steps"][0]
    assert tasks[3]["success"] and tasks[3]["off_path_ms"] > 0
    assert not tasks[4]["success"] and tasks[4]["ended_by"] == "gave_up"
    assert all(item["deviation_step"] is None for item in mock.session("guided_v0")["tasks"])


def test_index_and_sus_go_down_from_v0_to_v2(mock: Any) -> None:
    keys = ("guided_v0", "guided_v1", "guided_v2")
    bui = [mock.session(key)["usability_index"]["bui"] for key in keys]
    sus = [mock.session(key)["sus_score"] for key in keys]

    assert bui == sorted(bui, reverse=True) and len(set(bui)) == 3
    assert sus == sorted(sus, reverse=True) and len(set(sus)) == 3
    assert mock.session("free_v1")["usability_index"] is None


def test_the_index_follows_its_formulas(mock: Any) -> None:
    """El índice de V1, recalculado a mano con sus tareas, incidentes y referencias."""
    session = mock.session("guided_v1")
    references = {item["task_id"]: item for item in mock.truth["references"]}
    tasks = session["tasks"]
    done = [task for task in tasks if task["success"]]
    time_eff = (
        100
        * sum(min(1, references[t["task_id"]]["duration_ms"] / t["duration_ms"]) for t in done)
        / len(done)
    )
    path_eff = 100 * sum(min(1, t["path_steps"] / t["steps"]) for t in done) / len(done)
    minutes = sum(task["duration_ms"] for task in tasks) / 60_000
    per_minute = sum(1 for item in session["incidents"] if item["task_id"] is not None) / minutes
    friction = 100 * (1 - min(1, per_minute / mock.truth["friction_i_max"]))
    effectiveness = 100 * len(done) / len(tasks)
    index = session["usability_index"]

    assert index["time_efficiency"] == pytest.approx(time_eff, abs=0.01)
    assert index["path_efficiency"] == pytest.approx(path_eff, abs=0.01)
    assert index["friction"] == pytest.approx(friction, abs=0.01)
    assert index["bui"] == pytest.approx(
        (effectiveness + time_eff + path_eff + friction) / 4, abs=0.01
    )


# --- Coherencia entre la verdad, los eventos y los resultados ---------------------


def test_truth_matches_the_saved_results(mock: Any, mock_connection: sqlite3.Connection) -> None:
    for session in mock.truth["sessions"]:
        session_id = session["session_id"]
        saved = rows(
            mock_connection,
            "SELECT type, t, task_id FROM incident WHERE session_id = ? ORDER BY t, type",
            session_id,
        )
        expected = sorted(
            ((item["t_start"], item["type"]), item["task_id"]) for item in session["incidents"]
        )
        assert [((item["t"], item["type"]), item["task_id"]) for item in saved] == expected
        episodes = mock_connection.execute(
            "SELECT COUNT(*) FROM episode WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        assert episodes == len(session["episodes"])
        results = rows(
            mock_connection,
            "SELECT task_id, success, steps, deviation_step FROM"
            " task_result WHERE session_id = ? ORDER BY task_id",
            session_id,
        )
        assert results == [
            {
                "task_id": t["task_id"],
                "success": int(t["success"]),
                "steps": t["steps"],
                "deviation_step": t["deviation_step"],
            }
            for t in sorted(session["tasks"], key=lambda item: item["task_id"])
        ]
        index = rows(
            mock_connection,
            "SELECT bui, params_version FROM usability_index WHERE session_id = ?",
            session_id,
        )
        if session["usability_index"] is None:
            assert index == []
        else:
            assert index == [{"bui": session["usability_index"]["bui"], "params_version": "mock"}]


def test_task_results_match_the_recorded_tasks(
    mock: Any, mock_connection: sqlite3.Connection
) -> None:
    for session in mock.truth["sessions"]:
        recorded = {
            item["task_id"]: item
            for item in rows(
                mock_connection,
                "SELECT * FROM session_task WHERE session_id = ?",
                session["session_id"],
            )
        }
        for task in session["tasks"]:
            row = recorded[task["task_id"]]
            assert row["ended_by"] == task["ended_by"]
            assert row["t_end"] - row["t_start"] == pytest.approx(task["duration_ms"], abs=0.2)


def test_incidents_lie_within_their_session_and_task(
    mock: Any, mock_connection: sqlite3.Connection
) -> None:
    for session in mock.truth["sessions"]:
        tasks = {
            item["task_id"]: item
            for item in rows(
                mock_connection,
                "SELECT * FROM session_task WHERE session_id = ?",
                session["session_id"],
            )
        }
        for incident in session["incidents"]:
            assert (
                session["started_at"]
                <= incident["t_start"]
                <= incident["t_end"]
                <= session["ended_at"]
            )
            if incident["task_id"] is not None and incident["type"] != "task_overtime":
                task = tasks[incident["task_id"]]
                assert task["t_start"] <= incident["t_start"] <= task["t_end"], incident


def test_rage_clicks_in_the_truth_are_in_the_events(
    mock: Any, mock_connection: sqlite3.Connection, params: Parameters
) -> None:
    rage = params.rage_click
    for session, incident in incidents_of(mock, "rage_click"):
        clicks = [
            item
            for item in events(mock_connection, session["session_id"])
            if item["type"] == "click" and incident["t_start"] <= item["t"] <= incident["t_end"]
        ]
        assert len(clicks) >= rage.min_clicks
        assert clicks[-1]["t"] - clicks[0]["t"] <= rage.window_ms
        first = (clicks[0]["x"], clicks[0]["y"])
        assert all(math.dist(first, (item["x"], item["y"])) <= rage.radius_px for item in clicks)


def test_dead_clicks_are_exactly_the_clicks_without_response(
    mock: Any, mock_connection: sqlite3.Connection, params: Parameters
) -> None:
    """Un clic sin respuesta ni navegación en la espera es un dead click, y solo esos."""
    for session in mock.truth["sessions"]:
        stored = events(mock_connection, session["session_id"])
        answered = {item["data"]["click_t"] for item in stored if item["type"] == "click_response"}
        dead = set()
        for click in (item for item in stored if item["type"] == "click"):
            after = [
                item for item in stored if 0 < item["t"] - click["t"] <= params.dead_click.wait_ms
            ]
            focused = any(item["type"] == "focus_in" for item in after[:2])
            if click["t"] not in answered and not focused:
                dead.add(click["t"])
        expected = {
            item["t_start"] for item in session["incidents"] if item["type"] == "dead_click"
        }
        assert dead == expected, session["key"]


def test_long_pauses_are_exactly_the_long_gaps(
    mock: Any, mock_connection: sqlite3.Connection, params: Parameters
) -> None:
    for session in mock.truth["sessions"]:
        times = [item["t"] for item in events(mock_connection, session["session_id"])]
        gaps = {a for a, b in zip(times, times[1:], strict=False) if b - a > params.long_pause_ms}
        expected = {
            item["t_start"] for item in session["incidents"] if item["type"] == "long_pause"
        }
        assert gaps == expected, session["key"]


def test_task_overtime_follows_the_reference_duration(mock: Any, params: Parameters) -> None:
    references = {item["task_id"]: item["duration_ms"] for item in mock.truth["references"]}
    for session in mock.truth["sessions"]:
        flagged = {
            item["task_id"] for item in session["incidents"] if item["type"] == "task_overtime"
        }
        over = {
            task["task_id"]
            for task in session["tasks"]
            if task["duration_ms"] > params.task_overtime_factor * references[task["task_id"]]
        }
        assert flagged == over, session["key"]


# --- El pipeline sobre la base simulada --------------------------------------------


def test_the_pipeline_runs_on_the_mock_database(
    mock: Any, tmp_path: Path, params: Parameters
) -> None:
    copy = tmp_path / "copy.db"
    shutil.copy(mock.path, copy)

    with closing(db.open_database(copy)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in repository.list_sessions(mock.truth["study"]["id"]):
            results = analyze_session(repository, session.id, params)
            assert list(results.timings_ms)[-1] == "usability_index"


def test_cli_refuses_the_real_database_and_reports_each_session(
    mock: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """La generación completa ya la prueban las demás; aquí, solo la línea de comandos."""
    calls = []

    def fake_generate(database: Path, *, seed: int) -> dict[str, Any]:
        calls.append((database, seed))
        return mock.truth

    monkeypatch.setattr("scripts.generate_mock_data.generate", fake_generate)
    real = load_config().database.path

    assert main(["--db", str(real)]) == 1
    assert "is the real database" in capsys.readouterr().err
    assert main(["--db", "other.db", "--seed", "3"]) == 0
    assert calls == [(Path("other.db").resolve(), 3)]
    output = capsys.readouterr().out
    assert "session 5 (free_v1): 6 incidents" in output
    assert "ground truth: " in output
