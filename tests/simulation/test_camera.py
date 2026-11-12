"""Cámara simulada: los datos alcanzan para reprocesar, atribuir y medir el rostro."""

import shutil
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from analysis.gaze import GazeSettings
from analysis.loader import SqliteAnalysisRepository
from analysis.ml.facial import neutral_baseline
from analysis.parameters import load_parameters
from analysis.run import analyze_session
from dashboard import facial_insights
from dashboard.data import open_data
from scripts.simulation import scenarios
from scripts.simulation.builder import BuilderError, SessionBuilder
from scripts.simulation.camera import FACE_VALUES, NEUTRAL_BASELINE_MS, SimulatedEyes, iris_for
from shared import db
from shared.config import load_config


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory: pytest.TempPathFactory, mock: Any) -> Path:
    """Copia de la base simulada con todas sus sesiones analizadas, mirada incluida."""
    path = tmp_path_factory.mktemp("camera") / "mock.db"
    shutil.copy(mock.path, path)
    params = load_parameters()
    settings = GazeSettings.from_config(load_config().camera, params.gaze)
    with closing(db.open_database(path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in repository.list_sessions(1):
            analyze_session(repository, session.id, params, gaze=(repository, settings))
    return path


def test_the_iris_moves_with_the_point_looked_at() -> None:
    pose = {"yaw": 0, "pitch": -8, "distance": 58, "eye_u": 0.5, "eye_v": 0.45}
    pose |= {"aspect": 16 / 9, "open": 0.3}
    left, _ = iris_for(100, 400, pose)
    right, _ = iris_for(1100, 400, pose)
    _, top = iris_for(640, 100, pose)
    _, bottom = iris_for(640, 700, pose)
    assert left != right and top != bottom


def test_the_initial_calibration_starts_with_a_relaxed_face_and_follows_the_procedure() -> None:
    run = SimulatedEyes(1, (1280, 800)).calibration("initial", 0.0, 1.5, True)
    phases = [target["phase"] for target in run.targets]
    assert phases[0] == "neutral_baseline"
    assert phases[1:] == [
        *["points"] * 13,
        "pursuit",
        "head",
        *["validation"] * 8,
        "look_away",
    ]
    baseline = run.targets[0]
    assert baseline["t_end"] - baseline["t_start"] == NEUTRAL_BASELINE_MS
    # La mirada está en pausa durante la línea base: no hay cuadros en ese tramo.
    assert all(frame["t"] >= baseline["t_end"] for frame in run.frames)
    assert run.record["camera_delay_ms"] is not None and run.end > run.record["t"] - 1


def test_the_final_calibration_only_validates() -> None:
    run = SimulatedEyes(1, (1280, 800)).calibration("final", 0.0, 2.0, True)
    assert {target["phase"] for target in run.targets} == {"validation"}
    assert run.record["camera_delay_ms"] is None


def test_eyes_need_the_camera() -> None:
    with pytest.raises(BuilderError, match="camera"):
        SessionBuilder(study_id=1, mode="reference", eyes=True)


def test_a_session_with_eyes_has_every_camera_batch(context: scenarios.StudyContext) -> None:
    session = scenarios.guided_v1(context)
    batches = session.batches
    assert {"gaze_features", "gaze_target", "layout", "face", "gaze"} <= set(batches)
    assert batches["gaze_target"][0]["phase"] == "neutral_baseline"
    assert set(batches["face"][0]["values"]) == set(FACE_VALUES)
    screens = {layout["screen"]["url"] for layout in batches["layout"]}
    clicked = {event["screen"]["url"] for event in batches["events"] if event["type"] == "click"}
    assert clicked <= screens
    # La mirada en vivo se pausa durante las calibraciones, como en la extensión.
    initial = [t for t in batches["gaze_target"] if t["calibration_type"] == "initial"]
    start, end = initial[0]["t_start"], initial[-1]["t_end"]
    assert not any(start < sample["t"] < end for sample in batches["gaze"])


def test_the_refined_gaze_is_accurate_and_every_fixation_has_a_screen(analyzed: Path) -> None:
    with open_data(analyzed) as data:
        for session_id in (2, 3, 4, 5):
            fixations = data.get_gaze_fixations(session_id)
            assert len(fixations) > 20
            assert fixations["screen"].notna().all()
    with closing(db.open_database(analyzed)) as connection:
        errors = [
            row[0] for row in connection.execute("SELECT refined_error_deg FROM gaze_quality")
        ]
    assert len(errors) == 4
    assert all(error < 1.0 for error in errors)


def test_the_clicked_element_is_the_one_looked_at_before_the_click(analyzed: Path) -> None:
    """La persona simulada mira adonde va el cursor: al hacer clic, el elemento clicado.

    Se toma la última fijación que empezó antes del clic. No llega al 100 %:
    cuando el clic cambia de pantalla, la fijación sigue después del cambio y la
    atribución usa la disposición de la pantalla en que termina.
    """
    with open_data(analyzed) as data:
        events = data.get_events(3)
        fixations = data.get_gaze_fixations(3)
    hits, total = 0, 0
    for click in events[events["type"] == "click"].itertuples():
        selector = click.element.get("selector") if isinstance(click.element, dict) else None
        started = fixations[fixations["t_start"] <= click.t]
        if selector is None or started.empty:
            continue
        total += 1
        hits += int(started.iloc[-1]["element_selector"] == selector)
    assert total >= 20
    assert hits / total >= 0.7


def test_the_face_tenses_near_the_incidents(analyzed: Path) -> None:
    with open_data(analyzed) as data:
        session = data.get_session(4)
        incidents = data.get_incidents(study_id=1)
        face = data.get_face(4)
        targets = data.get_gaze_targets(4)
    baseline = neutral_baseline(face, targets)
    assert baseline.movements["brow_down"] < 0.15
    table = facial_insights.incident_comparison(
        face,
        targets,
        incidents[incidents["session_id"] == 4],
        float(session["started_at"]),
        float(session["ended_at"]),
    )
    brow = table.set_index("Movimiento").loc["Descenso de cejas"]
    assert brow["Junto al incidente"] - brow["Control"] > 0.2
    assert np.isfinite(brow["Control"])
