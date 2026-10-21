"""Genera la base de datos simulada y su verdad de referencia.

La base (por defecto, ``database.mock_path``) se recrea desde cero con el
estudio de ejemplo y estas sesiones:

- una grabación de referencia de las 4 tareas, con sus referencias confirmadas;
- tres sesiones guiadas (V0, V1 y V2) con problemas sembrados conocidos;
- una sesión libre.

Las tablas de resultados quedan llenas con los valores esperados, para que el
panel de resultados pueda avanzar antes que el análisis. Analizar una sesión de
esta base reemplaza esos resultados por los que calcule el pipeline.

Junto a la base se escribe ``<nombre>_ground_truth.json`` (por defecto,
``data/mock_ground_truth.json``) con los incidentes, episodios, resultados por
tarea e índice esperados de cada sesión, y las convenciones para compararlos.

Con la misma semilla, la base y la verdad son siempre idénticas.

Uso::

    python -m scripts.generate_mock_data
    python -m scripts.generate_mock_data --db data/otra.db --seed 3
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from analysis.parameters import Parameters, load_parameters
from scripts.simulation import scenarios, store
from scripts.simulation.builder import SimulatedSession
from server.services import sus_score
from shared import contracts
from shared.config import load_config

DEFAULT_SEED = 7
"""Semilla por defecto."""

MOCK_PARAMS_VERSION = "mock"
"""Versión con que se guardan los índices simulados: no los calculó el análisis."""

CONVENTIONS = {
    "screen": (
        "Ruta normalizada, sin dominio ni parámetros, con {id} en lugar de los identificadores."
    ),
    "incident": (
        "t_start y t_end delimitan el patrón (por ejemplo, del primer al último clic de una "
        "ráfaga). Un detector acierta si informa un incidente del mismo tipo, en la misma "
        "sesión, con t dentro de ese intervalo. En las tablas de resultados simuladas, "
        "t = t_start."
    ),
    "problem": "Número del problema sembrado (seeded_problems) que produce el incidente, o null.",
    "steps": "Clics en elementos interactivos, envíos de formulario y cambios de pantalla.",
    "deviation_step": (
        "Un paso está en la ruta si es el siguiente esperado de la referencia o repite uno ya "
        "hecho. El primer paso que no cumple esto es el desvío; deviation_step es la posición "
        "(desde 0) del paso esperado en ese momento, y off_path_ms suma el tiempo fuera de la "
        "ruta."
    ),
    "success": "La tarea llegó al final de su ruta, con los pasos obligatorios.",
    "usability_index": (
        "Fórmulas del índice con t_ref y pasos de la referencia; friction usa friction_i_max "
        "(incidentes por minuto de tarea)."
    ),
}
"""Cómo leer la verdad de referencia; se escribe en el propio archivo."""


def ground_truth_path(database: Path) -> Path:
    """Devuelve el archivo de la verdad de referencia de una base simulada.

    Args:
        database: Archivo de la base.

    Returns:
        ``<carpeta>/<nombre>_ground_truth.json``.
    """
    return database.with_name(f"{database.stem}_ground_truth.json")


def generate(
    database: Path, *, seed: int = DEFAULT_SEED, params: Parameters | None = None
) -> dict[str, Any]:
    """Recrea la base simulada y escribe su verdad de referencia.

    Args:
        database: Archivo de la base; si existe, se borra.
        seed: Semilla.
        params: Parámetros del análisis; por defecto, ``parameters.yaml``.

    Returns:
        La verdad de referencia, tal como se escribió.
    """
    params = params or load_parameters()
    connection = store.create_database(database)
    try:
        study = store.load_example_study(connection)
        context = scenarios.StudyContext(study.study_id, study.task_ids, params, seed)
        recording = scenarios.reference_recording(context)
        sessions = [("reference", recording, store.store_session(connection, recording))]
        conditions = {
            context.task_id(spec.position): (spec.end_condition, spec.candidates)
            for spec in scenarios.TASKS
        }
        reference_ids = store.store_references(
            connection, sessions[0][2], recording.references, conditions
        )
        durations = {item.task_id: item.duration_ms for item in recording.references}
        context = dataclasses.replace(context, reference_durations=durations)
        for key, scenario in scenarios.PARTICIPANT_SCENARIOS:
            built = scenario(context)
            sessions.append((key, built, store.store_session(connection, built)))
        for _, built, session_id in sessions:
            store.store_expected_results(connection, session_id, built.truth, MOCK_PARAMS_VERSION)
    finally:
        connection.close()

    truth = {
        "generated_by": "python -m scripts.generate_mock_data",
        "seed": seed,
        "params_version": params.version,
        "results_params_version": MOCK_PARAMS_VERSION,
        "contract_version": contracts.contract_version(),
        "friction_i_max": params.friction_i_max or scenarios.MOCK_FRICTION_I_MAX,
        "conventions": CONVENTIONS,
        "seeded_problems": {
            str(number): dict(problem) for number, problem in scenarios.SEEDED_PROBLEMS.items()
        },
        "study": {
            "id": study.study_id,
            "tasks": [
                {"id": task_id, "position": position}
                for position, task_id in enumerate(study.task_ids, start=1)
            ],
        },
        "references": [
            {
                "reference_id": reference_ids[item.task_id],
                "task_id": item.task_id,
                "source_session_id": sessions[0][2],
                "duration_ms": item.duration_ms,
                "steps": len(item.steps),
                "required_steps": list(item.required_steps),
                "end_condition": dict(conditions[item.task_id][0]),
            }
            for item in recording.references
        ],
        "sessions": [_session_truth(key, built, session_id) for key, built, session_id in sessions],
    }
    path = ground_truth_path(database)
    # Saltos de línea fijos para que el archivo sea idéntico byte a byte en Windows.
    text = json.dumps(truth, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return truth


def _session_truth(key: str, session: SimulatedSession, session_id: int) -> dict[str, Any]:
    """Verdad de referencia de una sesión, para el archivo JSON."""
    truth = session.truth
    return {
        "key": key,
        "session_id": session_id,
        "participant_id": session.request["participant_id"],
        "version": session.request["version"],
        "mode": session.request["mode"],
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "sus_score": None if session.sus_answers is None else sus_score(session.sus_answers),
        "incidents": [dataclasses.asdict(item) for item in truth.incidents],
        "episodes": [dataclasses.asdict(item) for item in truth.episodes],
        "tasks": [dataclasses.asdict(item) for item in truth.tasks],
        "usability_index": (
            None if truth.usability_index is None else dataclasses.asdict(truth.usability_index)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se generó, 1 si se rechazó la ruta.
    """
    parser = argparse.ArgumentParser(
        description="Recrea la base de datos simulada y su verdad de referencia."
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="ruta de la base (por defecto, database.mock_path de la configuración)",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="semilla (por defecto, 7)")
    args = parser.parse_args(argv)
    config = load_config()
    database = (args.db or config.database.mock_path).resolve()
    # La base simulada se borra y se recrea: nunca sobre la base de las sesiones reales.
    if database == config.database.path.resolve():
        print(
            f"error: {database} is the real database (database.path); use another path",
            file=sys.stderr,
        )
        return 1
    truth = generate(database, seed=args.seed)
    for session in truth["sessions"]:
        print(
            f"session {session['session_id']} ({session['key']}): "
            f"{len(session['incidents'])} incidents, {len(session['episodes'])} episodes, "
            f"{len(session['tasks'])} task results"
        )
    print(f"mock database: {database}")
    print(f"ground truth: {ground_truth_path(database)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
