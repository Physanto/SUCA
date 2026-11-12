"""Compara la atribución de una sesión con el guion de objetivos conocidos.

Uso: python -m scripts.attention_bench --session 17
     --script extension/test-page/attention-script.json --json data/attention-17.json
La sesión debe haberse procesado antes con analysis.run. No modifica la base.
"""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from analysis.gaze.attention_bench import AttentionScript, evaluate, render, report_to_json
from analysis.loader import NotFoundError, SqliteAnalysisRepository
from shared import db
from shared.config import ROOT_DIR, ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    """Carga los datos analizados y entrega el informe en consola y, opcionalmente, JSON."""
    parser = argparse.ArgumentParser(description="Mide la atribución contra un guion conocido.")
    parser.add_argument("--session", required=True, type=int)
    parser.add_argument(
        "--script", type=Path, default=ROOT_DIR / "extension/test-page/attention-script.json"
    )
    parser.add_argument("--db", type=Path, help="base de datos existente")
    parser.add_argument("--start-index", type=int, help="clic de inicio, desde cero")
    parser.add_argument("--json", type=Path, metavar="ARCHIVO")
    args = parser.parse_args(argv)
    try:
        script = AttentionScript.from_dict(json.loads(args.script.read_text(encoding="utf-8")))
        path = args.db if args.db is not None else load_config().database.path
        with closing(db.open_database(path)) as connection:
            repository = SqliteAnalysisRepository(connection)
            inputs = repository.load_gaze_inputs(args.session)
            fixations, candidates = repository.load_gaze_attention(args.session)
            states = repository.load_gaze_states(args.session)
        if fixations.empty:
            raise ValueError("no gaze attribution; run python -m analysis.run --session ID first")
        if states.empty:
            states = inputs.features[["t", "state"]]
        report = evaluate(
            inputs.interactions,
            fixations,
            candidates,
            states,
            inputs.layouts,
            script,
            start_index=args.start_index,
        )
        print(render(report))
        if args.json is not None:
            args.json.write_text(
                json.dumps(report_to_json(report), ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
    except (
        OSError,
        ValueError,
        ConfigError,
        NotFoundError,
        db.SchemaVersionError,
        sqlite3.Error,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
