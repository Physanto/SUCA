"""Evaluación completa sobre un experimento simulado y analizado."""

import json
from contextlib import closing
from pathlib import Path

import pytest

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import load_parameters
from analysis.run import analyze_session
from scripts import evaluate_study, simulate_experiment
from scripts.evaluation import report
from shared import db
from shared.problems import load_catalog

pytest.importorskip("scipy", reason="optional statistics dependencies: requirements-ml.txt")

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "studies" / "example-problems.yaml"


@pytest.fixture(scope="module")
def experiment(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Experimento simulado con 4 participantes por versión, ya analizado (sin la mirada)."""
    path = tmp_path_factory.mktemp("experiment") / "experiment.db"
    simulate_experiment.generate(path, per_version=4, seed=5, affected=1.0, false_alarm=1.0)
    params = load_parameters()
    with closing(db.open_database(path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in repository.list_sessions(1):
            analyze_session(repository, session.id, params)
    return path


def test_the_evaluation_answers_each_question(experiment: Path) -> None:
    params = load_parameters()
    params = type(params)(**{**params.__dict__, "friction_i_max": 15.0})
    truth = report.affected_from_truth(experiment.with_name("experiment_ground_truth.json"))
    with closing(db.open_database(experiment)) as connection:
        evaluation = report.evaluate(
            connection, 1, params, catalog=load_catalog(CATALOG), affected=truth, permutations=500
        )
    summary = evaluation.summary
    means = evaluation.tables["index_by_version"].set_index("version")["mean"]
    assert means["V0"] > means["V1"] > means["V2"]
    assert summary["p1"]["trend"]["p"] < 0.05
    assert summary["p2"]["spearman"]["n"] == 12
    # Todos los problemas afectaron a todos: los detectores encuentran casi todos.
    assert summary["p3"]["sensitivity"] >= 0.9
    # Todos se detuvieron a pensar en la tarea 1: en V0 son falsas alarmas.
    assert summary["p3"]["false_alarms_v0_per_session"] >= 1
    json.loads(report.to_json(evaluation))
    assert "P3 · Detección" in report.format_report(evaluation)


def test_without_friction_i_max_the_index_cannot_be_evaluated(experiment: Path) -> None:
    params = load_parameters()
    params = type(params)(**{**params.__dict__, "friction_i_max": None})
    with (
        closing(db.open_database(experiment)) as connection,
        pytest.raises(ValueError, match="friction_i_max"),
    ):
        report.evaluate(connection, 1, params)


def test_the_cli_writes_the_summary_the_tables_and_the_coding_template(
    experiment: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "evaluation"
    code = evaluate_study.main(
        [
            "--db",
            str(experiment),
            "--study",
            "1",
            "--friction-i-max",
            "15",
            "--catalog",
            str(CATALOG),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert "P1 · ¿El IUC distingue las versiones?" in capsys.readouterr().out
    assert json.loads((output / "summary.json").read_text(encoding="utf-8"))["summary"]["p3"]
    assert (output / "detection_by_problem.csv").exists()
    template = tmp_path / "coding.csv"
    assert (
        evaluate_study.main(
            ["--db", str(experiment), "--study", "1", "--coding-template", str(template)]
        )
        == 0
    )
    assert template.read_text(encoding="utf-8").startswith("session_id,participant_id")


def test_the_cli_reports_an_unknown_study(
    experiment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = evaluate_study.main(["--db", str(experiment), "--study", "9", "--friction-i-max", "15"])
    assert code == 1
    assert "study 9 does not exist" in capsys.readouterr().err
