"""Exporta ventanas de movimientos faciales y compara modelos con una persona fuera.

Uso: python -m scripts.facial_bench --study 1 --output data/facial-1 [--train]
Exige sesiones cerradas con línea base neutra marcada y análisis ya ejecutado.
No escribe en la base ni entrena modelos durante la captura.
"""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from analysis.loader import SqliteAnalysisRepository
from analysis.ml.facial import FEATURE_VERSION, FacialSettings
from analysis.ml.model import evaluate_models
from analysis.ml.windows import build_windows
from shared import db
from shared.config import load_config


def main(argv: list[str] | None = None) -> int:
    """Exporta datos locales, calidad y resultados de validación sin inferir emociones."""
    parser = argparse.ArgumentParser(description="Prepara ventanas faciales y compara señales.")
    parser.add_argument("--study", required=True, type=int)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="carpeta local de resultados")
    parser.add_argument("--train", action="store_true", help="entrena con scikit-learn instalado")
    args = parser.parse_args(argv)
    settings = FacialSettings()
    try:
        path = args.db if args.db is not None else load_config().database.path
        tables, skipped = [], []
        with closing(db.open_database(path)) as connection:
            repository = SqliteAnalysisRepository(connection)
            for session in repository.list_sessions(args.study):
                if not session.closed or session.mode == "reference":
                    continue
                data = repository.load_session(session.id)
                inputs = repository.load_gaze_inputs(session.id)
                fixations, _ = repository.load_gaze_attention(session.id)
                incidents, tasks = repository.load_facial_labels(session.id)
                try:
                    tables.append(
                        build_windows(data, inputs.targets, fixations, incidents, tasks, settings)
                    )
                except ValueError as error:
                    skipped.append({"session_id": session.id, "reason": str(error)})
        if not tables:
            raise ValueError("no sessions with a usable marked neutral baseline")
        windows = pd.concat(tables, ignore_index=True)
        report = {
            "feature_version": FEATURE_VERSION,
            "settings": asdict(settings),
            "skipped_sessions": skipped,
            "windows": len(windows),
        }
        if args.train:
            report["models"] = evaluate_models(windows)
        args.output.mkdir(parents=True, exist_ok=True)
        windows.to_csv(args.output / "windows.csv", index=False)
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        print(f"Exportadas {len(windows)} ventanas; {len(skipped)} sesiones omitidas.")
    except (OSError, ValueError, RuntimeError, LookupError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
