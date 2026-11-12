r"""Evalúa un estudio analizado: las preguntas P1 a P4 del experimento.

Lee la base (no escribe en ella) y calcula:

- **P1:** IUC por versión, ANOVA y Kruskal-Wallis, tendencia V0 > V1 > V2
  (Jonckheere-Terpstra) y consistencia por mitades de las tareas;
- **P2:** correlación de Spearman entre IUC y SUS y los casos discrepantes;
- **P3:** detección de cada problema sembrado del catálogo, falsas alarmas y
  precisión (con ``--catalog``); con ``--truth`` de un experimento simulado,
  también la sensibilidad de los detectores;
- **P4:** acuerdo de éxito y punto de desvío con la codificación manual
  (``--coding``). ``--coding-template`` escribe la plantilla para codificar.

Uso::

    python -m scripts.evaluate_study --study 1 --friction-i-max 15 \
        --catalog studies/example-problems.yaml --output data/evaluation
    python -m scripts.evaluate_study --study 1 --coding-template data/coding.csv
    python -m scripts.evaluate_study --study 1 --coding data/coding.csv

Requiere scipy (``pip install -r requirements-ml.txt``). Antes, analiza las
sesiones con ``python -m analysis.run --study ID``.
"""

import argparse
import dataclasses
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from analysis.parameters import ParametersError, load_parameters
from scripts.evaluation import agreement, report
from scripts.evaluation.repository import load_study_results
from shared import db
from shared.config import ConfigError, load_config
from shared.problems import CatalogError, load_catalog


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se evaluó, 1 si algo falló.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.evaluate_study",
        description="Evalúa un estudio analizado (preguntas P1 a P4).",
    )
    parser.add_argument("--study", type=int, required=True, metavar="ID", help="estudio")
    parser.add_argument("--db", type=Path, help="base (por defecto, database.path)")
    parser.add_argument("--catalog", type=Path, help="catálogo de problemas sembrados (P3)")
    parser.add_argument("--truth", type=Path, help="verdad de un experimento simulado (P3)")
    parser.add_argument("--coding", type=Path, help="codificación manual completada (P4)")
    parser.add_argument(
        "--coding-template", type=Path, help="escribe la plantilla de codificación y termina"
    )
    parser.add_argument(
        "--friction-i-max",
        type=float,
        help="normalización de la fricción del IUC si parameters.yaml no la define",
    )
    parser.add_argument(
        "--discrepancy", type=float, default=0.5, help="separación de rangos IUC–SUS (0 a 1)"
    )
    parser.add_argument("--output", type=Path, help="carpeta para el resumen JSON y las tablas CSV")
    args = parser.parse_args(argv)

    try:
        params = load_parameters()
        if args.friction_i_max is not None:
            params = dataclasses.replace(params, friction_i_max=args.friction_i_max)
        config = load_config()
        connection = db.open_database(args.db or config.database.path)
    except (ParametersError, ConfigError, FileNotFoundError, db.SchemaVersionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    with closing(connection):
        try:
            if args.coding_template:
                return _template(connection, args.study, args.coding_template)
            catalog = load_catalog(args.catalog) if args.catalog else None
            affected = report.affected_from_truth(args.truth) if args.truth else None
            coding = agreement.read_coding(args.coding) if args.coding else None
            evaluation = report.evaluate(
                connection,
                args.study,
                params,
                catalog=catalog,
                affected=affected,
                coding=coding,
                discrepancy=args.discrepancy,
            )
        except (LookupError, ValueError, RuntimeError, CatalogError, OSError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    print(report.format_report(evaluation))
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "summary.json").write_text(
            report.to_json(evaluation) + "\n", encoding="utf-8"
        )
        report.write_tables(evaluation, args.output)
        print(f"\nresults: {args.output}")
    return 0


def _template(connection: sqlite3.Connection, study_id: int, path: Path) -> int:
    """Escribe la plantilla de codificación manual de un estudio."""
    template = agreement.coding_template(load_study_results(connection, study_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    template.to_csv(path, index=False)
    print(f"coding template: {path} ({len(template)} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
