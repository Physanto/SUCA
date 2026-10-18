"""Prueba de integración: una sesión desde el servidor hasta el panel de resultados.

Una sesión simulada se envía por HTTP al servidor (como lo haría el worker de
la extensión), se analiza con un detector de prueba registrado y se lee desde
el acceso a datos del panel.
"""

import dataclasses
import warnings
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis import columns, detectors
from analysis.loader import SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters, load_parameters
from analysis.registry import Registry
from analysis.run import analyze_session
from dashboard.data import open_data
from scripts.simulation import scenarios, store
from scripts.simulation.builder import Click, SessionBuilder
from server.app import create_app
from shared import contracts, db
from shared.config import load_config

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*httpx.*")
    from fastapi.testclient import TestClient


class DeadImageClicks:
    """Detector de prueba: un ``dead_click`` por cada clic en un elemento no interactivo."""

    incident_type = "dead_click"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Marca los clics en elementos no interactivos."""
        rows = [
            {"type": "dead_click", "t": row.t, "screen": row.screen, "task_id": row.task_id,
             "element": row.element}
            for row in data.events[data.events["type"] == "click"].itertuples()
            if not row.element["interactive"]
        ]  # fmt: skip
        return columns.frame("incident", rows)


@pytest.fixture
def server(tmp_path: Path) -> Any:
    """Cliente HTTP de un servidor con una base nueva y el estudio de ejemplo."""
    path = tmp_path / "suca.db"
    store.create_database(path).close()
    config = load_config()
    config = dataclasses.replace(config, database=dataclasses.replace(config.database, path=path))
    with TestClient(create_app(config)) as client:
        client.headers["X-Api-Token"] = config.server.token
        client.database = path
        yield client


def send(client: Any, session: Any) -> int:
    """Envía una sesión simulada como lo haría la extensión: crear, lotes, SUS y cerrar."""
    session_id = client.post("/sessions", json=dict(session.request)).json()["session_id"]
    for batch_type, records in session.batches.items():
        batch = {"contract_version": contracts.contract_version(), "type": batch_type,
                 "records": list(records)}  # fmt: skip
        response = client.post(f"/sessions/{session_id}/batches", json=batch)
        assert response.status_code == 200, response.json()
    if session.sus_answers is not None:
        assert (
            client.post(
                f"/sessions/{session_id}/sus", json={"answers": list(session.sus_answers)}
            ).status_code
            == 200
        )
    assert client.post(f"/sessions/{session_id}/close").status_code == 200
    return session_id


def test_a_session_travels_from_the_server_to_the_dashboard(
    server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = (
        SessionBuilder(study_id=1, participant_id="E2E", mode="guided", seed=11)
        .with_calibration("initial", 1.5)
        .on_screen(scenarios.HOME)
        .with_task(1, scenarios.TASKS[0].path)
        .follow()
        .with_dead_click(scenarios.ZOOM_BADGE)
        .end_task("done")
        .with_sus([4, 2, 4, 2, 4, 2, 4, 2, 4, 2])
        .build()
    )
    registry = Registry("detector", key="incident_type", allowed=contracts.enums()["incident_type"])
    registry.register(DeadImageClicks)
    monkeypatch.setattr(detectors, "DETECTORS", registry)

    session_id = send(server, session)
    with closing(db.open_database(server.database)) as connection:
        results = analyze_session(
            SqliteAnalysisRepository(connection), session_id, load_parameters()
        )
    with open_data(server.database) as data:
        listed = data.get_sessions(study_id=1).set_index("session_id").loc[session_id]
        events = data.get_events(session_id)
        tasks = data.get_session_tasks(session_id)
        incidents = data.get_incidents(session_id=session_id)

    assert listed["participant_id"] == "E2E" and listed["sus_score"] == 75.0
    assert not pd.isna(listed["ended_at"])
    assert len(events) == len(session.batches["events"])
    assert tasks["ended_by"].tolist() == ["done"]
    expected = [item.t_start for item in session.truth.incidents if item.type == "dead_click"]
    assert list(results.incidents["t"]) == expected
    assert incidents["type"].tolist() == ["dead_click"]
    assert incidents.iloc[0]["element"]["id"] == "zoom-badge"


def test_the_server_rejects_a_batch_after_the_session_is_closed(server: Any) -> None:
    session = (
        SessionBuilder(study_id=1, seed=2)
        .on_screen(scenarios.HOME)
        .do(Click(scenarios.CART_LINK, to=scenarios.CART))
        .build()
    )
    session_id = send(server, session)
    batch = {"contract_version": contracts.contract_version(), "type": "events",
             "records": list(session.batches["events"][:1])}  # fmt: skip

    response = server.post(f"/sessions/{session_id}/batches", json=batch)

    assert response.status_code == 409
