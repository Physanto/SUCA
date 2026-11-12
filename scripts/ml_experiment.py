r"""Modelo de ventanas de 5 s con problemas sembrados: ¿qué señales aportan? (P5).

Arma una ventana de 5 s tras otra en cada sesión guiada cerrada del estudio,
con rasgos de interacción, mirada y rostro (``analysis/ml/features.py``). Cada
ventana vale 1 si la persona estaba ante un problema sembrado activo en su
versión, según el catálogo (``analysis/ml/labels.py``). Luego compara random
forest y gradient boosting con las reglas y entre señales, dejando un
participante fuera (``analysis/ml/signals.py``).

Uso::

    python -m scripts.ml_experiment --study 1 --catalog studies/example-problems.yaml \
        --output data/ml

Requiere las sesiones analizadas (``python -m analysis.run --study ID``) y
``pip install -r requirements-ml.txt``. Escribe ``windows.csv`` y
``report.json``; no escribe en la base.
"""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd

from analysis import cleaning, screens
from analysis.loader import SqliteAnalysisRepository
from analysis.ml.features import WINDOW_MS, session_windows
from analysis.ml.labels import problem_labels, rule_flags
from analysis.ml.signals import MODELS, compare_signals
from analysis.parameters import Parameters, ParametersError, load_parameters
from shared import db
from shared.config import ConfigError, load_config
from shared.problems import Catalog, CatalogError, load_catalog


def build_dataset(
    connection: sqlite3.Connection, study_id: int, catalog: Catalog, params: Parameters
) -> pd.DataFrame:
    """Ventanas etiquetadas de las sesiones guiadas y cerradas de un estudio.

    Args:
        connection: Base del estudio, ya analizado.
        study_id: Estudio.
        catalog: Problemas sembrados.
        params: Parámetros del análisis (limpieza y pantallas).

    Returns:
        Una fila por ventana con rasgos, ``label``, ``problems`` y ``rules``.

    Raises:
        ValueError: Si el estudio no tiene sesiones guiadas cerradas.
    """
    repository = SqliteAnalysisRepository(connection)
    positions = dict(
        connection.execute(
            "SELECT id, position FROM task WHERE study_id = ?", (study_id,)
        ).fetchall()
    )
    tables = []
    for session in repository.list_sessions(study_id):
        if not session.closed or session.mode != "guided":
            continue
        data = screens.assign_screens(
            cleaning.clean(repository.load_session(session.id), params), params
        )
        targets = repository.load_gaze_inputs(session.id).targets
        fixations, _ = repository.load_gaze_attention(session.id)
        incidents, _ = repository.load_facial_labels(session.id)
        windows = session_windows(data, targets, fixations)
        windows = windows.join(
            problem_labels(windows, data.events, session.version, catalog, positions)
        )
        tables.append(windows.assign(rules=rule_flags(windows, incidents)))
    if not tables:
        raise ValueError(f"study {study_id} has no closed guided sessions")
    return pd.concat(tables, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se entrenó, 1 si algo falló.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ml_experiment",
        description="Compara modelos, reglas y señales en ventanas de 5 s (P5).",
    )
    parser.add_argument("--study", type=int, required=True, metavar="ID", help="estudio")
    parser.add_argument("--catalog", type=Path, required=True, help="catálogo de problemas")
    parser.add_argument("--output", type=Path, required=True, help="carpeta de resultados")
    parser.add_argument("--db", type=Path, help="base (por defecto, database.path)")
    parser.add_argument("--seed", type=int, default=0, help="semilla de los modelos")
    args = parser.parse_args(argv)
    try:
        params = load_parameters()
        catalog = load_catalog(args.catalog)
        connection = db.open_database(args.db or load_config().database.path)
    except (
        ParametersError,
        ConfigError,
        CatalogError,
        FileNotFoundError,
        db.SchemaVersionError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        with closing(connection):
            windows = build_dataset(connection, args.study, catalog, params)
        result = compare_signals(windows, seed=args.seed)
    except (ValueError, RuntimeError, LookupError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    windows.to_csv(args.output / "windows.csv", index=False)
    report = {"window_ms": WINDOW_MS, "catalog": str(args.catalog), "seed": args.seed} | result
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(format_result(result))
    print(f"\nresults: {args.output}")
    return 0


def format_result(result: dict) -> str:
    """Resumen legible en español de la comparación."""

    def number(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}"

    lines = [
        f"Ventanas: {result['rows']} de {result['participants']} participantes "
        f"({100 * result['positive_share']:.0f} % ante un problema sembrado); "
        f"{result['excluded']} sin todos los rasgos.",
        "",
        "Exactitud equilibrada · AUC (fuera de muestra, un participante fuera)",
        f"  Reglas (algún incidente en la ventana): {number(result['rules']['balanced_accuracy'])}",
    ]
    names = {
        "interaction": "solo interacción",
        "interaction_gaze": "interacción + mirada",
        "all_signals": "interacción + mirada + rostro",
    }
    for model in MODELS:
        if model not in result["models"]:
            continue
        for variant, measures in result["models"][model].items():
            lines.append(
                f"  {model} · {names[variant]}: {number(measures['balanced_accuracy'])} · "
                f"{number(measures['roc_auc'])}"
            )
    for model, signals in result["importance_by_signal"].items():
        shares = ", ".join(f"{signal} {value:.3f}" for signal, value in signals.items())
        lines.append(f"  Importancia por señal ({model}): {shares}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
