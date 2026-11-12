"""Prueba de integración de la mirada: del servidor al reprocesamiento y al panel.

Una sesión simulada con deriva real (``tests/analysis/gaze_simulation.py``) se
envía por HTTP al servidor como lo haría la extensión: sus cuadros como lotes
``gaze_features`` y sus puntos de calibración como lotes ``gaze_target``, todos
validados contra los contratos. Después se analiza con la línea de comandos
real y se lee la mirada reprocesada desde el acceso a datos del panel.
"""

import dataclasses
import json
import math
import warnings
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from analysis import run
from dashboard.data import open_data
from scripts.simulation import store
from server.app import create_app
from shared import contracts
from shared.config import ROOT_DIR, load_config
from tests.analysis import gaze_simulation as sim

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*httpx.*")
    from fastapi.testclient import TestClient

#: Registros por lote, como `sending.max_batch_records` de la extensión.
BATCH_RECORDS = 500


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


def plain(value: Any) -> Any:
    """Valor de pandas como lo enviaría la extensión en JSON: NaN es null."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def records(frame: pd.DataFrame, rename: dict[str, str] | None = None) -> list[dict]:
    """Filas de un DataFrame como registros JSON."""
    return [
        {(rename or {}).get(key, key): plain(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def post_batches(client: Any, session_id: int, batch_type: str, items: list[dict]) -> None:
    """Envía registros en lotes del tamaño que usa la extensión."""
    for start in range(0, len(items), BATCH_RECORDS):
        batch = {
            "contract_version": contracts.contract_version(),
            "type": batch_type,
            "records": items[start : start + BATCH_RECORDS],
        }
        response = client.post(f"/sessions/{session_id}/batches", json=batch)
        assert response.status_code == 200, response.json()


def test_a_drifting_session_is_stored_refined_and_shown(
    server: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    simulation = sim.simulate(eye_drift_px_per_min=25.0, checks=3)
    body = json.loads((ROOT_DIR / "contracts" / "examples" / "new-session.valid.json").read_text())
    session_id = server.post("/sessions", json=body).json()["session_id"]

    post_batches(server, session_id, "gaze_features", records(simulation.frames))
    post_batches(server, session_id, "gaze_target", records(simulation.targets, {"t": "t_start"}))
    calibration = records(simulation.calibrations)[0]
    calibration = {key: value for key, value in calibration.items() if value is not None}
    post_batches(server, session_id, "calibration", [calibration])
    assert server.post(f"/sessions/{session_id}/close").status_code == 200

    exit_code = run.main(["--session", str(session_id), "--db", str(server.database)])

    assert exit_code == 0
    assert "gaze" in capsys.readouterr().out
    with open_data(server.database) as data:
        quality = data.get_gaze_quality(session_id)
        gaze = data.get_gaze(session_id, valid_only=False)
    assert quality["method"] == "geometric"
    assert bool(quality["drift_corrected"]) is True
    assert quality["refined_error_deg"] < quality["live_error_deg"]
    assert len(gaze) == len(simulation.frames)
    assert set(gaze["source"]) == {"refined"}
