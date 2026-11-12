"""Genera un experimento simulado: participantes entre sujetos en V0, V1 y V2.

Sirve para probar el análisis y la evaluación del experimento
(``scripts.evaluate_study``) antes de tener participantes. La base se recrea
desde cero con el estudio de ejemplo, la grabación de referencia y una sesión
guiada por participante (``scripts/simulation/experiment.py``), con ojos y
rostro simulados.

Las tablas de resultados quedan **vacías**: se llenan analizando la base, como
con datos reales. Junto a la base se escribe ``<nombre>_ground_truth.json`` con
la versión de cada participante, los problemas de su versión, los que le
afectaron y los incidentes, resultados e índice esperados.

Uso::

    python -m scripts.simulate_experiment --db data/experiment.db
    python -m analysis.run --db data/experiment.db --study 1
    python -m scripts.evaluate_study --db data/experiment.db --study 1

Con la misma semilla, la base y la verdad son siempre idénticas. Con 10
participantes por versión tarda unos minutos.
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from analysis.parameters import Parameters, load_parameters
from scripts.generate_mock_data import ground_truth_path, session_truth
from scripts.simulation import experiment, scenarios, store
from shared import contracts
from shared.config import load_config

DEFAULT_PER_VERSION = 10
"""Participantes por versión: los del diseño del experimento."""


def generate(
    database: Path,
    *,
    per_version: int = DEFAULT_PER_VERSION,
    seed: int = 7,
    affected: float = experiment.DEFAULT_AFFECTED,
    false_alarm: float = experiment.DEFAULT_FALSE_ALARM,
    params: Parameters | None = None,
) -> dict[str, Any]:
    """Recrea la base del experimento simulado y escribe su verdad.

    Args:
        database: Archivo de la base; si existe, se borra.
        per_version: Participantes por versión.
        seed: Semilla.
        affected: Probabilidad de que un problema de la versión afecte a un participante.
        false_alarm: Probabilidad de una pausa sin problema.
        params: Parámetros del análisis; por defecto, ``parameters.yaml``.

    Returns:
        La verdad, tal como se escribió.
    """
    params = params or load_parameters()
    plans = experiment.plan_experiment(
        per_version, seed=seed, affected=affected, false_alarm=false_alarm
    )
    connection = store.create_database(database)
    try:
        study = store.load_example_study(connection)
        context = scenarios.StudyContext(study.study_id, study.task_ids, params, seed)
        recording = scenarios.reference_recording(context)
        reference_session = store.store_session(connection, recording)
        conditions = {
            context.task_id(spec.position): (spec.end_condition, spec.candidates)
            for spec in scenarios.TASKS
        }
        store.store_references(connection, reference_session, recording.references, conditions)
        durations = {item.task_id: item.duration_ms for item in recording.references}
        context = dataclasses.replace(context, reference_durations=durations)
        sessions = []
        for plan in plans:
            built = experiment.participant_session(context, plan)
            session_id = store.store_session(connection, built)
            row = session_truth(plan.participant_id, built, session_id)
            row |= {
                "exposed_problems": list(plan.exposed),
                "affected_problems": list(plan.affected),
                "false_alarm": plan.false_alarm,
                "gave_up": plan.gave_up,
            }
            sessions.append(row)
    finally:
        connection.close()

    truth = {
        "generated_by": "python -m scripts.simulate_experiment",
        "seed": seed,
        "per_version": per_version,
        "affected_probability": affected,
        "false_alarm_probability": false_alarm,
        "params_version": params.version,
        "contract_version": contracts.contract_version(),
        "study": {"id": study.study_id, "task_ids": list(study.task_ids)},
        "reference_session_id": reference_session,
        "versions": {version: list(problems) for version, problems in experiment.VERSIONS.items()},
        "seeded_problems": {
            str(number): dict(problem) for number, problem in scenarios.SEEDED_PROBLEMS.items()
        },
        "sessions": sessions,
    }
    path = ground_truth_path(database)
    text = json.dumps(truth, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return truth


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se generó, 1 si se rechazó la ruta o un valor.
    """
    parser = argparse.ArgumentParser(
        description="Genera un experimento simulado entre sujetos (V0, V1 y V2)."
    )
    parser.add_argument("--db", type=Path, required=True, help="base nueva del experimento")
    parser.add_argument(
        "--per-version", type=int, default=DEFAULT_PER_VERSION, help="participantes por versión"
    )
    parser.add_argument("--seed", type=int, default=7, help="semilla (por defecto, 7)")
    parser.add_argument(
        "--affected",
        type=float,
        default=experiment.DEFAULT_AFFECTED,
        help="probabilidad de que un problema afecte a un participante",
    )
    parser.add_argument(
        "--false-alarm",
        type=float,
        default=experiment.DEFAULT_FALSE_ALARM,
        help="probabilidad de una pausa sin problema",
    )
    args = parser.parse_args(argv)
    config = load_config()
    database = args.db.resolve()
    # La base se borra y se recrea: nunca sobre la base de las sesiones reales.
    if database == config.database.path.resolve():
        print(
            f"error: {database} is the real database (database.path); use another path",
            file=sys.stderr,
        )
        return 1
    try:
        truth = generate(
            database,
            per_version=args.per_version,
            seed=args.seed,
            affected=args.affected,
            false_alarm=args.false_alarm,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for session in truth["sessions"]:
        print(
            f"session {session['session_id']} ({session['participant_id']}, "
            f"{session['version']}): affected by {session['affected_problems'] or 'none'}"
        )
    print(f"experiment database: {database}")
    print(f"ground truth: {ground_truth_path(database)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
