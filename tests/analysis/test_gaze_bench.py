"""Pruebas de la medición de la mirada.

Cubren el modelo geométrico, las muestras con objetivo, el banco de pruebas, la
carga desde la base y la línea de comandos.
"""

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.gaze import GazeSettings
from analysis.gaze.bench import evaluate, render
from analysis.gaze.model import FEATURE_COLUMNS, fit_geometric, project
from analysis.gaze.samples import events, geometric_features, px_to_deg, target_samples
from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import load_parameters
from scripts import gaze_bench
from server.ingestion import handler_for
from server.repositories import SqliteRepository
from shared.config import ROOT_DIR
from tests.analysis import gaze_simulation as sim

EXAMPLES = ROOT_DIR / "contracts" / "examples"


@pytest.fixture(scope="module")
def simulation() -> sim.Simulation:
    """Sesión simulada, la misma para todas las pruebas del módulo."""
    return sim.simulate()


@pytest.fixture
def settings() -> GazeSettings:
    """Ajustes con la pantalla de la simulación."""
    return GazeSettings(
        css_px_per_cm=sim.CSS_PX_PER_CM,
        viewing_distance_cm=60.0,
        blink_threshold=0.45,
        params=load_parameters().gaze,
    )


def test_python_and_the_extension_project_gaze_the_same_way() -> None:
    """Las mismas cuentas en los dos lenguajes: el reprocesamiento repite lo de la extensión."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    frame = {
        "yaw": 7.5,
        "pitch": -12.0,
        "distance": 61.0,
        "eyeU": 0.46,
        "eyeV": 0.41,
        "aspect": 1.7778,
        "h": 0.04,
        "v": -0.02,
        "open": 0.31,
    }
    script = (
        "require('./extension/camera/numeric.js');require('./extension/camera/gaze-model.js');"
        "require('./extension/camera/gaze-geometry.js');"
        f"const p=UX.gazeGeometry.project({json.dumps(list(sim.TRUTH))},{json.dumps(frame)},"
        "{cssPxPerCm:40,openRef:0.3});process.stdout.write(JSON.stringify(p));"
    )
    expected = json.loads(
        subprocess.run(
            [node, "-e", script], capture_output=True, text=True, check=True, cwd=ROOT_DIR
        ).stdout
    )
    features = pd.DataFrame([{**frame, "eye_u": frame["eyeU"], "eye_v": frame["eyeV"]}])[
        list(FEATURE_COLUMNS)
    ]

    x, y = project(sim.TRUTH, features, 40.0, 0.3)

    assert abs(x[0] - expected["x"]) < 1e-6 and abs(y[0] - expected["y"]) < 1e-6


def test_the_simulated_person_looks_where_the_true_model_says(simulation: sim.Simulation) -> None:
    features = geometric_features(simulation.frames)

    x, y = project(sim.TRUTH, features, sim.CSS_PX_PER_CM, sim.OPEN_REF)

    # El ruido del iris (±0,0015 anchos de ojo por ojo) mueve el punto unos pocos píxeles.
    error = np.hypot(x - simulation.truth["x"], y - simulation.truth["y"])
    assert np.median(error) < 15


def test_the_geometric_model_trained_on_the_calibration_works_in_another_posture(
    simulation: sim.Simulation,
) -> None:
    samples = target_samples(
        simulation.frames,
        simulation.targets,
        blink_threshold=0.45,
        pursuit_skip_ms=1000,
        delay_ms=sim.DELAY_MS,
    )
    features = geometric_features(simulation.frames)
    train = samples[samples["phase"].isin(["points", "pursuit", "head"])]
    later = samples[samples["calibration_type"] == "drift_check"]

    fit = fit_geometric(
        features.loc[train["frame"]],
        train["target_x"],
        train["target_y"],
        train["group"],
        viewport_width=sim.VIEWPORT[0],
        css_px_per_cm=sim.CSS_PX_PER_CM,
    )
    x, y = fit.model.predict(features.loc[later["frame"]])

    assert fit.groups == 13 + 4 + 1
    error = np.hypot(x - later["target_x"].to_numpy(), y - later["target_y"].to_numpy())
    # A 66 cm y 40 px/cm, un grado son unos 46 px.
    assert error.mean() < 40, f"mean error {error.mean():.1f} px"
    assert abs(fit.model.named_params()["g_yaw"] - 1) < 0.15


def test_the_model_needs_four_targets() -> None:
    features = pd.DataFrame([dict.fromkeys(FEATURE_COLUMNS, 0.5)] * 3)

    fit = fit_geometric(
        features, [1, 2, 3], [1, 2, 3], ["a", "b", "c"], viewport_width=1000, css_px_per_cm=40
    )

    assert (fit.model, fit.cv_error_px, fit.groups) == (None, None, 3)


def test_samples_follow_the_moving_point_with_the_camera_delay_and_skip_blinks(
    simulation: sim.Simulation,
) -> None:
    frames = simulation.frames.copy()
    frames.loc[frames.index[0], "blink"] = 0.9

    samples = target_samples(
        frames,
        simulation.targets,
        blink_threshold=0.45,
        pursuit_skip_ms=1000,
        delay_ms=sim.DELAY_MS,
    )

    assert frames.index[0] not in set(samples["frame"])
    pursuit = samples[samples["phase"] == "pursuit"]
    truth = simulation.truth.loc[pursuit["frame"]]
    assert np.allclose(pursuit["target_x"], truth["x"], atol=1.5)
    assert pursuit["group"].nunique() == 4
    assert (
        pursuit["t"].min()
        >= simulation.targets.loc[simulation.targets["phase"] == "pursuit", "t"].iloc[0] + 1000
    )


def test_targets_of_one_procedure_share_an_event_number(simulation: sim.Simulation) -> None:
    numbers = events(simulation.targets)

    by_type = numbers.groupby(simulation.targets["calibration_type"]).unique()
    assert list(by_type["initial"]) == [0]
    assert list(by_type["drift_check"]) == [1]


def test_degrees_depend_on_the_distance() -> None:
    assert px_to_deg(np.array([40.0]), np.array([60.0]), 40.0)[0] == pytest.approx(
        np.degrees(np.arctan(1 / 60))
    )


def test_the_bench_measures_live_and_refitted_gaze(
    simulation: sim.Simulation, settings: GazeSettings
) -> None:
    report = evaluate(simulation.frames, simulation.targets, simulation.calibrations, settings)

    summary = report.summary
    assert summary["camera_delay_ms"] == sim.DELAY_MS
    assert summary["refit_deg"] < 1.0
    # La mirada en vivo de la simulación se corre 12 px por minuto: a los 5 minutos son unos 2°.
    assert summary["live_drift_deg"] > 1.0
    assert summary["live_precision_deg"] > 0
    assert set(report.by_phase["phase"]) == {
        "points",
        "pursuit",
        "head",
        "validation",
        "look_away",
        "drift_check",
    }
    assert len(report.by_region) == 9
    assert set(report.by_pose["factor"]) == {"yaw_deg", "pitch_deg", "distance_cm"}
    assert list(report.over_time["calibration_type"]) == ["initial", "drift_check"]
    assert set(report.states["state"]) >= {"on_screen", "blink", "off_screen"}
    text = render(report)
    assert "Por región de la pantalla" in text and "refit_deg" in text


def test_the_bench_without_targets_reports_only_the_summary(
    simulation: sim.Simulation, settings: GazeSettings
) -> None:
    report = evaluate(
        simulation.frames, simulation.targets.iloc[0:0], simulation.calibrations, settings
    )

    assert report.summary["samples"] == 0
    assert report.by_phase.empty


def _store_examples(connection: sqlite3.Connection, tmp_path: Path) -> None:
    """Guarda los ejemplos de los contratos en la sesión 1, con los manejadores del servidor."""
    writer = SqliteRepository(connection, tmp_path)
    for batch_type, name in (
        ("gaze_features", "gaze_features.valid.json"),
        ("gaze_target", "gaze_target.valid.json"),
        ("layout", "layout.valid.json"),
        ("calibration", "calibration.valid.json"),
    ):
        with writer.transaction():
            handler_for(batch_type)(
                writer, 1, [json.loads((EXAMPLES / name).read_text(encoding="utf-8"))]
            )


def test_the_repository_loads_what_the_server_stored(
    connection: sqlite3.Connection, repository: SqliteAnalysisRepository, tmp_path: Path
) -> None:
    _store_examples(connection, tmp_path)

    inputs = repository.load_gaze_inputs(1)

    assert inputs.features.iloc[0]["left_refined"] == True  # noqa: E712 (booleano de pandas)
    assert inputs.features.iloc[0]["state"] == "on_screen"
    assert inputs.targets.iloc[0]["points"] == [{"t": 1791380123456.2, "x": 128, "y": 72}]
    assert inputs.layouts.iloc[0]["regions"][0]["zone"] == "header"
    assert inputs.calibrations.iloc[-1]["estimator"] == "geometric"


def test_the_command_line_prints_the_report_and_saves_json(
    connection: sqlite3.Connection,
    analysis_db: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _store_examples(connection, tmp_path)
    connection.commit()
    out = tmp_path / "report.json"

    assert gaze_bench.main(["--session", "1", "--db", str(analysis_db), "--json", str(out)]) == 0

    assert "Resumen" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["frames"] == 1


def test_the_command_line_explains_a_session_without_gaze_features(
    analysis_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gaze_bench.main(["--session", "1", "--db", str(analysis_db)]) == 1
    assert "no gaze features" in capsys.readouterr().err
