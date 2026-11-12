"""Experimento simulado: reparto entre sujetos, problemas por versión y SUS."""

import dataclasses
import json
import random
from pathlib import Path

import pytest

from scripts import simulate_experiment
from scripts.simulation import experiment, scenarios
from scripts.simulation.builder import BuilderError, SessionBuilder
from server.services import sus_score
from shared import db
from shared.config import load_config


def test_the_assignment_is_balanced_and_deterministic() -> None:
    plans = experiment.plan_experiment(5, seed=3)
    assert [plan.version for plan in plans].count("V0") == 5
    assert [plan.version for plan in plans].count("V1") == 5
    assert [plan.version for plan in plans].count("V2") == 5
    assert plans == experiment.plan_experiment(5, seed=3)
    assert plans != experiment.plan_experiment(5, seed=4)


def test_only_the_problems_of_each_version_can_affect_a_participant() -> None:
    for plan in experiment.plan_experiment(10, seed=1):
        assert plan.exposed == experiment.VERSIONS[plan.version]
        assert set(plan.affected) <= set(plan.exposed)
        assert not plan.gave_up or plan.version == "V2"


def test_the_sus_goes_down_with_the_version() -> None:
    plans = experiment.plan_experiment(10, seed=2)
    mean = {
        version: sum(sus_score(p.sus_answers) for p in plans if p.version == version) / 10
        for version in experiment.VERSIONS
    }
    assert mean["V0"] > mean["V1"] > mean["V2"]


@pytest.mark.parametrize("score", [0.0, 37.5, 80.0, 100.0])
def test_the_sus_answers_land_near_the_score(score: float) -> None:
    answers = experiment.sus_answers_for(score, random.Random(0))
    assert all(1 <= answer <= 5 for answer in answers) and len(answers) == 10
    assert abs(sus_score(answers) - score) <= 20


def test_invalid_plans_are_refused() -> None:
    with pytest.raises(ValueError, match="per_version"):
        experiment.plan_experiment(0)
    with pytest.raises(ValueError, match="probabilities"):
        experiment.plan_experiment(2, affected=1.5)


def test_each_affected_problem_leaves_its_incidents(context: scenarios.StudyContext) -> None:
    """Cualquier combinación de problemas se puede construir y deja su rastro."""
    plans = experiment.plan_experiment(4, seed=5, affected=0.5, false_alarm=1.0)
    for plan in plans:
        session = experiment.participant_session(context, plan)
        seeded = {item.problem for item in session.truth.incidents if item.problem}
        assert seeded == set(plan.affected)
        # La pausa sin problema es un incidente que ningún problema sembrado explica.
        assert any(
            item.type == "long_pause" and item.problem is None for item in session.truth.incidents
        )


def test_a_participant_who_gives_up_fails_the_last_task(context: scenarios.StudyContext) -> None:
    plan = dataclasses.replace(
        experiment.plan_experiment(1, seed=1)[0], version="V2", affected=(3, 5), gave_up=True
    )
    session = experiment.participant_session(context, plan)
    assert [task.success for task in session.truth.tasks] == [True, True, True, False]


def test_the_generator_writes_the_sessions_and_their_truth(tmp_path: Path) -> None:
    path = tmp_path / "experiment.db"
    truth = simulate_experiment.generate(path, per_version=1, seed=2)
    stored = json.loads((tmp_path / "experiment_ground_truth.json").read_text(encoding="utf-8"))
    assert stored == truth
    assert sorted(item["version"] for item in truth["sessions"]) == ["V0", "V1", "V2"]
    connection = db.open_database(path)
    try:
        sessions = connection.execute("SELECT COUNT(*) FROM session").fetchone()[0]
        incidents = connection.execute("SELECT COUNT(*) FROM incident").fetchone()[0]
        references = connection.execute(
            "SELECT COUNT(*) FROM reference WHERE status = 'confirmed'"
        ).fetchone()[0]
    finally:
        connection.close()
    # Referencia y 3 participantes; los resultados se llenan al analizar, como con datos reales.
    assert sessions == 4 and incidents == 0 and references == 4


def test_the_cli_refuses_the_real_database(capsys: pytest.CaptureFixture[str]) -> None:
    real = load_config().database.path
    assert simulate_experiment.main(["--db", str(real)]) == 1
    assert "real database" in capsys.readouterr().err


def test_a_pause_at_the_start_of_a_task_is_refused(context: scenarios.StudyContext) -> None:
    """El detector no ve una pausa entre un evento fuera de la tarea y el primero de ella."""
    builder = SessionBuilder(study_id=1, mode="guided", camera=False).on_screen(scenarios.LOGIN)
    builder.do(scenarios.LOGIN_ACTION).with_task(1, scenarios.TASKS[0].path)
    with pytest.raises(BuilderError, match="same task"):
        builder.with_long_pause()
