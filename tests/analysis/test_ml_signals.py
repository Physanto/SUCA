"""Modelo de ventanas de 5 s: rasgos, etiquetas por problema sembrado y comparación."""

from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis import cleaning, columns, screens
from analysis.loader import SqliteAnalysisRepository
from analysis.ml.features import (
    FACE_FEATURES,
    GAZE_FEATURES,
    INTERACTION_FEATURES,
    WINDOW_MS,
    session_windows,
)
from analysis.ml.labels import problem_labels, rule_flags
from analysis.ml.signals import compare_signals, make_model
from analysis.parameters import load_parameters
from analysis.run import analyze_session
from scripts import ml_experiment, simulate_experiment
from scripts.simulation import scenarios, store
from shared import db
from shared.problems import load_catalog

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "studies" / "example-problems.yaml")
POSITIONS = {1: 1, 2: 2, 3: 3, 4: 4}


@pytest.fixture(scope="module")
def sessions(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Sesiones simuladas en V0 y V1, cargadas como las recibe el modelo."""
    params = load_parameters()
    base = scenarios.StudyContext(1, (1, 2, 3, 4), params)
    recording = scenarios.reference_recording(base)
    durations = {item.task_id: item.duration_ms for item in recording.references}
    context = scenarios.StudyContext(1, (1, 2, 3, 4), params, reference_durations=durations)
    connection = store.create_database(tmp_path_factory.mktemp("ml") / "ml.db")
    store.load_example_study(connection)
    loaded = {}
    for key, scenario in (("V0", scenarios.guided_v0), ("V1", scenarios.guided_v1)):
        built = scenario(context)
        data = store.load_session(connection, built)
        targets = columns.frame(
            "gaze_targets",
            [
                {**target, "t": target["t_start"], "t_end": target["t_end"]}
                for target in built.batches["gaze_target"]
            ],
        )
        loaded[key] = (screens.assign_screens(cleaning.clean(data, params), params), targets, built)
    connection.close()
    return loaded


def test_windows_last_five_seconds_and_skip_the_calibrations(sessions: dict) -> None:
    data, targets, _ = sessions["V1"]
    windows = session_windows(data, targets, columns.empty("gaze_fixation"))
    assert (windows["t_end"] - windows["t_start"] == WINDOW_MS).all()
    initial_end = targets.loc[targets["calibration_type"] == "initial", "t_end"].max()
    final = targets[targets["calibration_type"] == "final"]
    assert windows["t_start"].min() >= initial_end
    for row in final.itertuples():
        assert not ((windows["t_start"] < row.t_end) & (windows["t_end"] > row.t)).any()
    assert set(INTERACTION_FEATURES + GAZE_FEATURES + FACE_FEATURES) <= set(windows)
    # Hubo clics, mirada y una línea base neutra: ningún grupo de rasgos queda vacío.
    assert windows["clicks"].sum() > 0
    assert windows["gaze_valid_share"].notna().all()
    assert windows[list(FACE_FEATURES)].notna().all(axis=1).mean() > 0.8


def test_labels_mark_the_places_of_the_active_problems_only(sessions: dict) -> None:
    labelled = {}
    for version in ("V0", "V1"):
        data, targets, _ = sessions[version]
        windows = session_windows(data, targets, columns.empty("gaze_fixation"))
        labelled[version] = problem_labels(windows, data.events, version, CATALOG, POSITIONS)
    assert labelled["V0"]["label"].sum() == 0
    v1 = labelled["V1"]
    assert v1["label"].sum() > 0
    present = {number for numbers in v1["problems"] for number in numbers}
    assert present == {1, 2, 3, 4}


def test_rule_flags_mark_the_windows_with_an_incident() -> None:
    windows = pd.DataFrame({"t_start": [0.0, 5000.0, 10000.0], "t_end": [5000.0, 10000.0, 15000.0]})
    flags = rule_flags(windows, pd.DataFrame({"t": [4999.0, 12000.0]}))
    assert flags.tolist() == [1, 0, 1]
    assert rule_flags(windows, pd.DataFrame({"t": []})).tolist() == [0, 0, 0]


def _synthetic(participants: int = 6, seed: int = 1) -> pd.DataFrame:
    """Ventanas falsas donde los clics y el ceño suben ante un problema."""
    rng = np.random.default_rng(seed)
    rows = []
    for person in range(participants):
        for _ in range(40):
            label = int(rng.random() < 0.3)
            row = {
                name: rng.normal()
                for name in (*INTERACTION_FEATURES, *GAZE_FEATURES, *FACE_FEATURES)
            }
            row["clicks"] += 2.0 * label
            row["brow_down_delta"] += 2.0 * label
            rows.append(
                row
                | {
                    "label": label,
                    "rules": label if rng.random() < 0.6 else 0,
                    "participant_id": f"P{person}",
                }
            )
    return pd.DataFrame(rows)


def test_the_models_learn_from_the_signals_and_beat_chance() -> None:
    pytest.importorskip("sklearn", reason="optional ML dependencies: requirements-ml.txt")
    result = compare_signals(_synthetic(), importance_repeats=2)
    assert result["participants"] == 6 and result["excluded"] == 0
    for model in ("random_forest", "gradient_boosting"):
        assert result["models"][model]["all_signals"]["balanced_accuracy"] > 0.75
        assert result["models"][model]["all_signals"]["roc_auc"] > 0.8
    importance = result["importance"]["random_forest"]
    assert max(importance, key=importance.get) in {"clicks", "brow_down_delta"}
    assert result["rules"]["roc_auc"] is None and result["rules"]["recall"] < 1


def test_windows_without_every_signal_are_left_out_of_all_variants() -> None:
    pytest.importorskip("sklearn", reason="optional ML dependencies: requirements-ml.txt")
    windows = _synthetic()
    windows.loc[:9, "brow_down_delta"] = np.nan
    result = compare_signals(windows, models=("random_forest",), importance_repeats=1)
    assert result["excluded"] == 10 and result["rows"] == len(windows) - 10


def test_too_few_participants_or_classes_are_refused() -> None:
    pytest.importorskip("sklearn", reason="optional ML dependencies: requirements-ml.txt")
    with pytest.raises(ValueError, match="participants"):
        compare_signals(_synthetic(participants=2))
    single = _synthetic().assign(label=0)
    with pytest.raises(ValueError, match="one class"):
        compare_signals(single)
    with pytest.raises(ValueError, match="unknown model"):
        make_model("deep_net")


def test_the_cli_builds_the_dataset_and_compares(tmp_path: Path) -> None:
    pytest.importorskip("sklearn", reason="optional ML dependencies: requirements-ml.txt")
    path = tmp_path / "experiment.db"
    simulate_experiment.generate(path, per_version=2, seed=4, affected=1.0)
    params = load_parameters()
    with closing(db.open_database(path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in repository.list_sessions(1):
            analyze_session(repository, session.id, params)
        dataset = ml_experiment.build_dataset(connection, 1, CATALOG, params)
    assert set(dataset["version"]) == {"V0", "V1", "V2"}
    assert dataset.loc[dataset["version"] == "V0", "label"].sum() == 0
    assert dataset["rules"].sum() > 0
    output = tmp_path / "ml"
    code = ml_experiment.main(
        [
            "--db",
            str(path),
            "--study",
            "1",
            "--catalog",
            str(ROOT / "studies" / "example-problems.yaml"),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert (output / "windows.csv").exists() and (output / "report.json").exists()


def test_the_cli_reports_a_study_without_sessions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "empty.db"
    store.create_database(path).close()
    code = ml_experiment.main(
        [
            "--db",
            str(path),
            "--study",
            "1",
            "--catalog",
            str(ROOT / "studies" / "example-problems.yaml"),
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 1
    assert "no closed guided sessions" in capsys.readouterr().err


def test_facial_windows_can_last_up_to_five_seconds() -> None:
    from analysis.ml.facial import FacialSettings

    assert FacialSettings(window_ms=WINDOW_MS).window_ms == 5000
    with pytest.raises(ValueError, match="between 1000 and 5000"):
        FacialSettings(window_ms=6000)
