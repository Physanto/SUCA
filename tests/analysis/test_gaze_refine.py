"""Pruebas del reprocesamiento de la mirada al cerrar la sesión.

Cubren el reajuste con la sesión simulada (con y sin deriva real), la medición
honesta del error, el suavizado, las fijaciones, la zona y el elemento con la
disposición registrada, el guardado y la integración en el orquestador.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis import columns
from analysis.gaze import GazeSettings
from analysis.gaze.layout import assign, grid_zone
from analysis.gaze.refine import GEOMETRIC, LIVE, refine
from analysis.loader import GazeInputs, SessionInfo, SqliteAnalysisRepository
from analysis.parameters import Parameters, load_parameters
from analysis.run import analyze_session, summary
from server.ingestion import handler_for
from server.repositories import SqliteRepository
from shared import contracts
from shared.config import ROOT_DIR
from tests.analysis import gaze_simulation as sim

SESSION = SessionInfo(
    id=1,
    study_id=1,
    participant_id="P1",
    version="V0",
    mode="guided",
    started_at=sim.T0,
    ended_at=sim.T0 + 600_000,
    screen_info=None,
)


@pytest.fixture
def settings() -> GazeSettings:
    """Ajustes con la pantalla de la simulación."""
    return GazeSettings(
        css_px_per_cm=sim.CSS_PX_PER_CM,
        viewing_distance_cm=60.0,
        blink_threshold=0.45,
        params=load_parameters().gaze,
    )


def inputs_of(simulation: sim.Simulation, layouts: pd.DataFrame | None = None) -> GazeInputs:
    """Datos de mirada de una sesión simulada, como los entrega el repositorio."""
    return GazeInputs(
        session=SESSION,
        features=simulation.frames,
        targets=simulation.targets,
        calibrations=simulation.calibrations,
        layouts=columns.empty("layouts") if layouts is None else layouts,
        gaze=columns.empty("gaze"),
    )


def test_looking_states_come_from_the_contract() -> None:
    from analysis.gaze.refine import LOOKING

    assert set(LOOKING) <= set(contracts.enums()["gaze_state"])


def test_refits_the_model_and_beats_the_drifting_live_gaze(settings: GazeSettings) -> None:
    simulation = sim.simulate()

    refined = refine(inputs_of(simulation), settings)

    quality = refined.quality.iloc[0]
    assert quality["method"] == GEOMETRIC
    assert quality["refined_error_deg"] < 1.0
    assert quality["refined_error_deg"] < quality["live_error_deg"]
    assert quality["camera_delay_ms"] == sim.DELAY_MS
    columns.validate(refined.samples, "gaze_refined")
    assert len(refined.samples) == len(simulation.frames)
    # Fuera de los procedimientos, el punto refinado está cerca de lo que se miraba de verdad.
    looking = refined.samples["valid"].to_numpy()
    error = np.hypot(
        refined.samples["x"].to_numpy(float)[looking] - simulation.truth["x"].to_numpy()[looking],
        refined.samples["y"].to_numpy(float)[looking] - simulation.truth["y"].to_numpy()[looking],
    )
    assert np.median(error) < 40, f"median error {np.median(error):.1f} px"


def test_corrects_a_real_drift_of_the_person_measured_without_cheating(
    settings: GazeSettings,
) -> None:
    drifting = refine(inputs_of(sim.simulate(eye_drift_px_per_min=25.0, checks=3)), settings)
    steady = refine(inputs_of(sim.simulate()), settings)

    quality = drifting.quality.iloc[0]
    assert bool(quality["drift_corrected"]) is True
    # Medido sin usar cada control para corregirse a sí mismo.
    assert quality["refined_error_deg"] < 0.7
    assert quality["refined_error_deg"] < quality["live_error_deg"]
    # Sin deriva real no hay nada que corregir: basta el modelo de la calibración.
    assert bool(steady.quality.iloc[0]["drift_corrected"]) is False
    assert steady.quality.iloc[0]["fit_scope"] == "calibration"


def test_keeps_the_live_gaze_when_the_refit_does_not_beat_it(settings: GazeSettings) -> None:
    """Con una mirada en vivo exacta, ningún reajuste puede mejorarla."""
    simulation = sim.simulate()
    frames = simulation.frames.assign(
        raw_x=simulation.truth["x"].to_numpy(), raw_y=simulation.truth["y"].to_numpy()
    )
    exact = GazeInputs(**{**inputs_of(simulation).__dict__, "features": frames})

    quality = refine(exact, settings).quality.iloc[0]

    assert quality["method"] == LIVE
    assert quality["refined_error_deg"] == quality["live_error_deg"]


def test_blinks_and_looking_away_have_no_refined_point(settings: GazeSettings) -> None:
    simulation = sim.simulate()

    samples = refine(inputs_of(simulation), settings).samples

    away = samples[samples["state"].isin(["off_screen", "blink"])]
    assert len(away) > 0
    assert away["x"].isna().all() and not away["valid"].any()


def test_smoothing_steadies_fixations_and_finds_them(settings: GazeSettings) -> None:
    simulation = sim.simulate()

    samples = refine(inputs_of(simulation), settings).samples

    # Cada punto de validación es una fijación: casi todas sus muestras quedan en una sola.
    targets = simulation.targets[simulation.targets["phase"] == "validation"]
    for _, target in targets.iterrows():
        inside = samples[(samples["t"] >= target["t"] + 200) & (samples["t"] <= target["t_end"])]
        assert inside["fixation"].notna().mean() > 0.8
        assert inside["fixation"].nunique() <= 2


def test_without_a_calibration_the_live_gaze_is_only_smoothed(settings: GazeSettings) -> None:
    simulation = sim.simulate()
    no_targets = inputs_of(simulation)
    no_targets = GazeInputs(**{**no_targets.__dict__, "targets": columns.empty("gaze_targets")})

    refined = refine(no_targets, settings)

    quality = refined.quality.iloc[0]
    assert quality["method"] == LIVE
    assert pd.isna(quality["refined_error_deg"])
    assert refined.samples["valid"].any()


def test_no_frames_give_empty_tables(settings: GazeSettings) -> None:
    empty = GazeInputs(
        session=SESSION,
        features=columns.empty("gaze_features"),
        targets=columns.empty("gaze_targets"),
        calibrations=columns.empty("gaze_calibrations"),
        layouts=columns.empty("layouts"),
        gaze=columns.empty("gaze"),
    )

    refined = refine(empty, settings)

    assert refined.samples.empty and refined.quality.empty


def layout(t: float, *, scroll_y: float) -> dict:
    """Disposición con un encabezado fijo y un contenido principal desplazado."""
    return {
        "t": t,
        "screen": {"url": "https://shop.local/", "title": "Tienda"},
        "viewport_width": 1000.0,
        "viewport_height": 600.0,
        "scroll_x": 0.0,
        "scroll_y": scroll_y,
        "regions": [
            {"zone": "header", "box": {"x": 0, "y": 0, "w": 1000, "h": 60}, "fixed": True},
            {
                "zone": "main",
                "box": {"x": 0, "y": 60 - scroll_y, "w": 1000, "h": 2000},
                "fixed": False,
            },
        ],
        "elements": [
            {
                "selector": "#logo",
                "tag": "a",
                "role": "link",
                "box": {"x": 10, "y": 10, "w": 100, "h": 40},
                "fixed": True,
            },
            {
                "selector": "#buy",
                "tag": "button",
                "role": "button",
                "box": {"x": 400, "y": 500 - scroll_y, "w": 200, "h": 50},
                "fixed": False,
            },
        ],
        "truncated": False,
    }


def test_zone_and_element_follow_the_layout_and_the_scroll() -> None:
    layouts = columns.frame("layouts", [layout(1000, scroll_y=0)])
    points = pd.DataFrame(
        {
            # Logo; botón sin scroll; botón tras bajar 300 px (el registro es anterior al scroll);
            # contenido sin elemento; punto sin mirada; punto anterior a toda disposición.
            "t": [2000, 2000, 3000, 3000, 3000, 500],
            "x": [50, 500, 500, 900, np.nan, 500],
            "y": [30, 520, 220, 400, np.nan, 520],
            "scroll_x": [0, 0, 0, 0, 0, 0],
            "scroll_y": [0, 0, 300, 300, 300, 0],
            "viewport_width": [1000] * 6,
            "viewport_height": [600] * 6,
        }
    )

    places = assign(points, layouts)

    assert list(places["zone"]) == ["header", "main", "main", "main", None, "grid_bottom_center"]
    assert list(places["element_selector"]) == ["#logo", "#buy", "#buy", None, None, None]


def test_grid_zones_use_the_names_of_the_contract() -> None:
    names = grid_zone(
        np.array([0, 999, 500]), np.array([0, 599, 300]), np.array([1000] * 3), np.array([600] * 3)
    )

    assert names == ["grid_top_left", "grid_bottom_right", "grid_middle_center"]
    assert set(names) <= set(contracts.enums()["gaze_zone"])


def _store(connection: sqlite3.Connection, tmp_path: Path) -> None:
    """Guarda en la sesión 1 un cuadro de mirada y una disposición, como el servidor."""
    writer = SqliteRepository(connection, tmp_path)
    examples = ROOT_DIR / "contracts" / "examples"
    for batch_type, name in (
        ("gaze_features", "gaze_features.valid.json"),
        ("layout", "layout.valid.json"),
    ):
        with writer.transaction():
            handler_for(batch_type)(
                writer, 1, [json.loads((examples / name).read_text(encoding="utf-8"))]
            )


def test_the_refinement_is_saved_and_replaced(
    connection: sqlite3.Connection,
    repository: SqliteAnalysisRepository,
    settings: GazeSettings,
    tmp_path: Path,
) -> None:
    _store(connection, tmp_path)
    refined = refine(repository.load_gaze_inputs(1), settings)

    repository.save_gaze_refinement(1, refined.samples, refined.quality)
    repository.save_gaze_refinement(1, refined.samples, refined.quality)

    rows = connection.execute("SELECT zone, valid FROM gaze_refined").fetchall()
    # El ejemplo mira por debajo del contenido principal registrado: zona de la cuadrícula.
    assert [tuple(row) for row in rows] == [("grid_middle_center", 1)]
    quality = connection.execute("SELECT method, fit_scope FROM gaze_quality").fetchone()
    assert tuple(quality) == (LIVE, None)


def test_an_invalid_refinement_leaves_the_database_untouched(
    connection: sqlite3.Connection, repository: SqliteAnalysisRepository
) -> None:
    broken = pd.DataFrame({"t": [1.0]})

    with pytest.raises(columns.ColumnValidationError):
        repository.save_gaze_refinement(1, broken, columns.empty("gaze_quality"))
    assert connection.execute("SELECT COUNT(*) FROM gaze_refined").fetchone()[0] == 0


def test_the_analysis_refines_the_gaze_after_saving_its_results(
    connection: sqlite3.Connection,
    repository: SqliteAnalysisRepository,
    params: Parameters,
    settings: GazeSettings,
    tmp_path: Path,
) -> None:
    _store(connection, tmp_path)

    results = analyze_session(repository, 1, params, gaze=(repository, settings))

    assert results.gaze_quality.iloc[0]["method"] == LIVE
    assert "gaze live" in summary(results)
    assert connection.execute("SELECT COUNT(*) FROM gaze_refined").fetchone()[0] == 1


def test_a_failed_refinement_does_not_undo_the_analysis(
    repository: SqliteAnalysisRepository,
    params: Parameters,
    settings: GazeSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken:
        def load_gaze_inputs(self, session_id: int) -> GazeInputs:
            raise RuntimeError("disk on fire")

        def save_gaze_refinement(self, *args: object) -> None:  # pragma: no cover
            raise AssertionError("must not save")

    results = analyze_session(repository, 1, params, gaze=(Broken(), settings))

    assert results.gaze_quality is None
    assert "gaze refinement failed: disk on fire" in caplog.text
    assert len(results.usability_index) <= 1


def test_each_session_uses_the_screen_and_distance_it_recorded(settings: GazeSettings) -> None:
    calibrations = pd.DataFrame(
        {
            "t": [1.0, 2.0, 3.0],
            "type": ["initial", "drift_check", "initial"],
            "css_px_per_cm": [40.0, None, 36.2],
            "viewing_distance_cm": [48.0, 50.0, None],
        }
    )

    session = settings.for_session(calibrations)

    # La última calibración con pantalla manda; la distancia es la mediana de las medidas.
    assert session.css_px_per_cm == 36.2
    assert session.viewing_distance_cm == 49.0
    assert session.params is settings.params


def test_sessions_without_screen_data_keep_the_configuration(settings: GazeSettings) -> None:
    old = pd.DataFrame({"t": [1.0], "type": ["initial"], "viewing_distance_cm": [None]})

    assert settings.for_session(old) == settings
    assert settings.for_session(columns.empty("gaze_calibrations")) == settings
