"""Reproduce una grabación real de la página de prueba por HTTP, análisis y confirmación."""

import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import load_parameters
from analysis.run import analyze_session
from dashboard.data import DashboardData
from scripts.init_db import init_db
from scripts.load_study import load_study, read_study
from server import routes
from server.app import create_app
from shared import contracts, db
from shared.config import ROOT_DIR, load_config

FIXTURE = Path(__file__).with_name("fixtures") / "reference_test_page.json"


def test_recorded_reference_proposes_the_correct_condition_and_can_be_confirmed(
    tmp_path: Path,
) -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    recording = document["recording"]
    captured = recording["events"]
    # Son clics reales del módulo provisional; no se añaden eventos de navegación.
    assert [event["type"] for event in captured] == ["click", "click"]
    assert [event["element"]["text"] for event in captured] == [
        "Otra página",
        "Botón de la otra página",
    ]
    assert captured[-1]["screen"]["url"] == recording["final_url"]
    for event in captured:
        assert contracts.validate("events", event) == []

    path = tmp_path / "recorded.db"
    init_db(path)
    with closing(db.open_database(path)) as connection:
        study = load_study(connection, read_study(ROOT_DIR / "studies" / "example.yaml"))
    config = load_config()
    config = replace(config, database=replace(config.database, path=path))
    app = create_app(config)
    app.dependency_overrides[routes.get_clock] = lambda: lambda: recording["t_start"]
    with TestClient(app, headers={"X-Api-Token": config.server.token}) as client:
        response = client.post(
            "/sessions",
            json={
                "study_id": study.study_id,
                "participant_id": "RECORDED-REF",
                "version": "test-page",
                "mode": "reference",
                "screen_info": recording["screen_info"],
            },
        )
        assert response.status_code == 201, response.json()
        session_id = response.json()["session_id"]
        for kind, records in (
            ("events", captured),
            (
                "tasks",
                [
                    {
                        "task_id": study.task_ids[0],
                        "t_start": recording["t_start"],
                        "t_end": recording["t_end"],
                        "ended_by": "done",
                    }
                ],
            ),
        ):
            response = client.post(
                f"/sessions/{session_id}/batches",
                json={
                    "contract_version": contracts.contract_version(),
                    "type": kind,
                    "records": records,
                },
            )
            assert response.status_code == 200, response.json()
        response = client.post(
            "/references",
            json={
                "task_id": study.task_ids[0],
                "source_session_id": session_id,
            },
        )
        assert response.status_code == 201, response.json()
        reference_id = response.json()["reference_id"]
        app.dependency_overrides[routes.get_clock] = lambda: lambda: recording["t_end"]
        assert client.post(f"/sessions/{session_id}/close").status_code == 200

    correct = {"type": "url_pattern", "pattern": "/extension/test-page/second-page.html"}
    with closing(db.open_database(path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        result = analyze_session(repository, session_id, load_parameters())
        assert len(result.reference_drafts) == 1
        draft = result.reference_drafts.iloc[0]
        assert correct in draft["candidates"]
        assert {
            "type": "element_present",
            "text": "Botón de la otra página",
            "role": "button",
        } in draft["candidates"]
        assert draft["steps"] == [
            {name: event[name] for name in ("t", "type", "screen", "element")} for event in captured
        ]
        row = connection.execute("SELECT * FROM reference WHERE id = ?", (reference_id,)).fetchone()
        assert row["status"] == "draft" and row["end_condition"] is None
        assert json.loads(row["candidates"]) == draft["candidates"]
        DashboardData(connection, tmp_path).confirm_reference(reference_id, correct, [0, 1])
        confirmed = dict(
            connection.execute("SELECT * FROM reference WHERE id = ?", (reference_id,)).fetchone()
        )
        analyze_session(repository, session_id, load_parameters())
        assert (
            dict(
                connection.execute(
                    "SELECT * FROM reference WHERE id = ?", (reference_id,)
                ).fetchone()
            )
            == confirmed
        )
        assert confirmed["status"] == "confirmed"
        assert len(repository.load_session(session_id).references) == 1
