"""Pruebas del orquestador del análisis y de su línea de comandos."""

import dataclasses
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from analysis import cleaning, columns, detectors, reference, run
from analysis.loader import SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.registry import Registry
from analysis.run import StageError, analyze_session, main, run_pipeline
from shared import contracts


class ClickProbe:
    """Detector de prueba: un ``dead_click`` por cada clic de la sesión."""

    incident_type = "dead_click"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Marca cada clic."""
        clicks = data.events[data.events["type"] == "click"]
        return columns.frame(
            "incident",
            [
                {
                    "type": "dead_click",
                    "t": row.t,
                    "screen": row.screen,
                    "task_id": row.task_id,
                    "element": row.element,
                }
                for row in clicks.itertuples()
            ],
        )


@pytest.fixture
def probe_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registra ``ClickProbe`` solo durante la prueba."""
    registry = Registry("detector", key="incident_type", allowed=contracts.enums()["incident_type"])
    registry.register(ClickProbe)
    monkeypatch.setattr(detectors, "DETECTORS", registry)


def close_session_2(connection: sqlite3.Connection) -> None:
    """Cierra la sesión libre de la base pequeña."""
    connection.execute("UPDATE session SET ended_at = started_at + 5000 WHERE id = 2")


def test_runs_every_stage_in_order_with_screen_episodes(
    repository: SqliteAnalysisRepository, params: Parameters
) -> None:
    results = run_pipeline(repository.load_session(1), params)

    assert list(results.timings_ms) == [stage.name for stage in run.STAGES]
    assert list(results.timings_ms) == [
        "cleaning",
        "screens",
        "episodes",
        "detectors",
        "reference_drafts",
        "reference",
        "usability_index",
    ]
    assert all(duration >= 0 for duration in results.timings_ms.values())
    assert results.episodes["screen"].tolist() == ["/cart/{id}", "/order/{id}"]
    columns.validate(results.episodes, "episode")
    for table, frame in [
        ("incident", results.incidents),
        ("usability_index", results.usability_index),
        ("reference_draft", results.reference_drafts),
    ]:
        assert len(frame) == 0
        columns.validate(frame, table)
    assert len(results.task_results) == 1
    assert not results.task_results.iloc[0]["success"]
    columns.validate(results.task_results, "task_result")


def test_logs_the_time_of_each_stage(
    repository: SqliteAnalysisRepository, params: Parameters, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="analysis"):
        run_pipeline(repository.load_session(1), params)

    assert [message.split(" took")[0] for message in caplog.messages] == [
        f"session 1: {stage.name}" for stage in run.STAGES
    ]


def test_a_registered_detector_appears_in_the_saved_results(
    repository: SqliteAnalysisRepository,
    params: Parameters,
    connection: sqlite3.Connection,
    probe_detector: None,
) -> None:
    results = analyze_session(repository, 1, params)

    assert list(results.incidents["type"]) == ["dead_click"]
    rows = [dict(row) for row in connection.execute("SELECT * FROM incident")]
    assert [(row["session_id"], row["type"], row["task_id"]) for row in rows] == [
        (1, "dead_click", 1)
    ]
    assert rows[0]["screen"] == "/cart/{id}"


def test_analyzing_twice_does_not_duplicate_results(
    repository: SqliteAnalysisRepository,
    params: Parameters,
    count_rows: Callable[[str], int],
    probe_detector: None,
) -> None:
    analyze_session(repository, 1, params)
    analyze_session(repository, 1, params)

    assert count_rows("incident") == 1


def test_a_failing_stage_stops_with_its_name_and_saves_nothing(
    repository: SqliteAnalysisRepository,
    params: Parameters,
    count_rows: Callable[[str], int],
    probe_detector: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_session(repository, 1, params)

    def broken(data: SessionData, params: Parameters) -> pd.DataFrame:
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(reference, "compare", broken)

    with pytest.raises(StageError, match="stage 'reference' failed: division by zero") as raised:
        analyze_session(repository, 1, params)
    assert raised.value.stage == "reference"
    # Los resultados del análisis anterior siguen ahí.
    assert count_rows("incident") == 1


def test_a_stage_with_wrong_columns_is_rejected(
    repository: SqliteAnalysisRepository, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reference, "compare", lambda data, params: pd.DataFrame({"task": [1]}))

    with pytest.raises(StageError, match="stage 'reference' failed: task_result: missing columns"):
        run_pipeline(repository.load_session(1), params)


def test_a_data_stage_must_keep_the_session_data(
    repository: SqliteAnalysisRepository, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drops_screen(data: SessionData, params: Parameters) -> SessionData:
        return dataclasses.replace(data, events=data.events.drop(columns=["screen"]))

    monkeypatch.setattr(cleaning, "clean", drops_screen)

    with pytest.raises(StageError, match=r"stage 'cleaning' failed: .*\(events\): missing columns"):
        run_pipeline(repository.load_session(1), params)


def test_an_open_session_is_analyzed_with_a_warning(
    repository: SqliteAnalysisRepository, params: Parameters, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="analysis"):
        analyze_session(repository, 2, params)

    assert "session 2 is still open" in caplog.text


def test_cli_analyzes_one_session(analysis_db: Path, capsys: pytest.CaptureFixture) -> None:
    code = main(["--session", "1", "--db", str(analysis_db)])

    output = capsys.readouterr().out
    assert code == 0
    assert output.startswith("session 1: 2 episodes, 0 incidents, 1 task results, no index (")


def test_cli_analyzes_the_closed_sessions_of_a_study(
    analysis_db: Path, capsys: pytest.CaptureFixture
) -> None:
    code = main(["--study", "1", "--db", str(analysis_db)])

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines[0] == "session 2: skipped (still open)"
    assert lines[1].startswith("session 1: ")
    assert len(lines) == 2


def test_cli_continues_with_the_other_sessions_when_one_fails(
    analysis_db: Path,
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    close_session_2(connection)

    def fails_on_session_1(data: SessionData, params: Parameters) -> pd.DataFrame:
        if data.session.id == 1:
            raise ValueError("bad reference")
        return columns.empty("task_result")

    monkeypatch.setattr(reference, "compare", fails_on_session_1)

    code = main(["--study", "1", "--db", str(analysis_db)])

    captured = capsys.readouterr()
    assert code == 1
    assert "error: session 1: stage 'reference' failed: bad reference" in captured.err
    assert captured.out.startswith("session 2: ")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--session", "99"], "error: session 99: session 99 not found"),
        (["--study", "99"], "error: study 99 not found"),
    ],
)
def test_cli_reports_unknown_sessions_and_studies(
    analysis_db: Path, capsys: pytest.CaptureFixture, args: list[str], message: str
) -> None:
    code = main([*args, "--db", str(analysis_db)])

    assert code == 1
    assert message in capsys.readouterr().err


def test_cli_reports_a_missing_database(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    code = main(["--session", "1", "--db", str(tmp_path / "missing.db")])

    assert code == 1
    assert "database not found" in capsys.readouterr().err


def test_cli_needs_exactly_one_target(analysis_db: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--db", str(analysis_db)])
    with pytest.raises(SystemExit):
        main(["--session", "1", "--study", "1", "--db", str(analysis_db)])
