"""Detección de los problemas sembrados, falsas alarmas y acuerdo manual."""

from pathlib import Path

import pandas as pd
import pytest

from scripts.evaluation import agreement, detection
from scripts.evaluation.repository import StudyResults
from shared.problems import load_catalog

CATALOG = load_catalog(Path(__file__).resolve().parents[2] / "studies" / "example-problems.yaml")


def results() -> StudyResults:
    """Tres sesiones: V0 con una pausa, V1 con la imagen que parece botón y V1 sin nada."""
    sessions = pd.DataFrame(
        {
            "session_id": [1, 2, 3],
            "participant_id": ["A", "B", "C"],
            "version": ["V0", "V1", "V1"],
            "sus": [80.0, 60.0, 70.0],
        }
    )
    tasks = pd.DataFrame({"task_id": [11, 12, 13, 14], "position": [1, 2, 3, 4]})
    task_results = pd.DataFrame(
        [
            {
                "session_id": s,
                "task_id": 10 + p,
                "position": p,
                "success": not (s == 3 and p == 4),
                "duration_ms": 10_000.0,
                "steps": 4,
                "deviation_step": 2 if (s, p) == (2, 3) else None,
                "off_path_ms": 0.0,
            }
            for s in (1, 2, 3)
            for p in (1, 2, 3, 4)
            if not (s == 3 and p == 4)
        ]
    )
    incidents = pd.DataFrame(
        {
            "session_id": [1, 2, 2],
            "type": ["long_pause", "dead_click", "long_pause"],
            "t": [1.0, 2.0, 3.0],
            "screen": ["/search", "/product/{id}", "/cart"],
            "task_id": [11, 12, 12],
            "position": pd.array([1, 2, 2], dtype="Int64"),
        }
    )
    return StudyResults(sessions, tasks, task_results, incidents, pd.DataFrame())


def test_a_problem_is_detected_by_an_incident_of_its_type_task_and_screen() -> None:
    found = detection.session_detection(results(), CATALOG)
    image = found[(found["session_id"] == 2) & (found["problem"] == 1)].iloc[0]
    assert image["detected"] and image["evidence"] == 1
    # La V1 sin incidentes estuvo expuesta a los 4 problemas y no se detectó ninguno.
    other = found[found["session_id"] == 3]
    assert other["problem"].tolist() == [1, 2, 3, 4]
    assert not other["detected"].any()
    # No hizo la tarea 4: no estuvo expuesta al problema 3.
    assert not other.set_index("problem").at[3, "exposed"]


def test_v0_has_no_problems_and_its_incidents_are_false_alarms() -> None:
    alarms = detection.false_alarms(results(), CATALOG).set_index("version")
    assert alarms.at["V0", "unmatched"] == 1 and pd.isna(alarms.at["V0", "precision"])
    # En V1: la imagen se explica; la pausa en el carrito, no.
    assert alarms.at["V1", "matched"] == 1 and alarms.at["V1", "unmatched"] == 1
    assert alarms.at["V1", "precision"] == pytest.approx(0.5)
    types = detection.unmatched_by_type(results(), CATALOG)
    assert types["type"].tolist() == ["long_pause", "long_pause"]


def test_the_summary_uses_only_exposed_sessions_and_the_truth_when_given() -> None:
    found = detection.session_detection(results(), CATALOG, {2: {1}, 3: {1, 2}})
    summary = detection.problem_summary(found, CATALOG).set_index("problem")
    assert summary.at[1, "exposed"] == 2 and summary.at[1, "detected"] == 1
    assert summary.at[1, "affected"] == 2 and summary.at[1, "sensitivity"] == pytest.approx(0.5)
    assert summary.at[3, "exposed"] == 1
    assert summary.at[5, "exposed"] == 0 and pd.isna(summary.at[5, "detection_rate"])


def test_the_coding_template_round_trips_and_measures_agreement(tmp_path: Path) -> None:
    template = agreement.coding_template(results())
    assert len(template) == 11
    assert (
        template.loc[
            (template["session_id"] == 2) & (template["task_position"] == 3), "auto_deviation_step"
        ].item()
        == "2"
    )
    template["manual_success"] = template["auto_success"].astype(str)
    template.loc[0, "manual_success"] = "0"  # Una tarea que el evaluador ve fallida.
    template["manual_deviation_step"] = template["auto_deviation_step"]
    template.loc[5, "manual_deviation_step"] = ""  # Sin codificar.
    path = tmp_path / "coding.csv"
    template.to_csv(path, index=False)
    result = agreement.coding_agreement(agreement.read_coding(path))
    assert result["success"]["n"] == 11
    assert result["success"]["agreement"] == pytest.approx(10 / 11)
    assert result["deviation"]["n"] == 10 and result["deviation"]["agreement"] == 1.0
    assert result["deviation"]["within_one_step"] == 1.0


@pytest.mark.parametrize(
    ("column", "value"), [("manual_success", "sí"), ("manual_deviation_step", "tres")]
)
def test_invalid_manual_codes_are_refused(tmp_path: Path, column: str, value: str) -> None:
    template = agreement.coding_template(results())
    template.loc[0, column] = value
    path = tmp_path / "coding.csv"
    template.to_csv(path, index=False)
    with pytest.raises(ValueError, match=column):
        agreement.read_coding(path)
