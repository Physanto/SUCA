"""Migra de forma conservadora una base del esquema 7 al 8, con respaldo previo.

Uso: python -m scripts.migrate_db --db data/otra.db
Detén primero el servidor y el análisis. No admite versiones anteriores a 7:
una base simulada antigua se regenera con scripts.generate_mock_data.
"""

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from shared import db
from shared.config import load_config


def migrate(path: Path, backup_path: Path | None = None) -> Path | None:
    """Agrega las tablas de atribución y la pantalla de calibración sin borrar datos.

    Args:
        path: Base existente en versión 7, u 8 para comprobar idempotencia.
        backup_path: Destino nuevo para el respaldo SQLite consistente, incluido WAL.

    Returns:
        Ruta del respaldo previo, o None si la base ya estaba actualizada.

    Raises:
        ValueError: Si la versión no es migrable o hay objetos de atribución incompatibles.
        FileExistsError: Si ya existe el destino del respaldo.
        sqlite3.Error: Si la migración falla; se revierte completa.
    """
    with closing(db.connect(path)) as connection:
        version = db.schema_version(connection)
        calibration_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(calibration)")
        }
        if version not in ("7", "8"):
            raise ValueError(f"only schema 7 or 8 can be migrated, found {version!r}")
        with closing(sqlite3.connect(":memory:")) as canonical:
            canonical.row_factory = sqlite3.Row
            db.create_schema(canonical)
            definitions = canonical.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE tbl_name IN"
                " ('gaze_fixation', 'gaze_attribution') AND sql IS NOT NULL"
                " ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name"
            ).fetchall()
        existing_objects = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE tbl_name IN"
                " ('gaze_fixation', 'gaze_attribution') AND sql IS NOT NULL"
            ).fetchall()
        )
        if (
            version == "8"
            and "css_px_per_cm" in calibration_columns
            and all(existing_objects.get(d["name"]) == d["sql"] for d in definitions)
        ):
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_path or path.with_name(
            f"{path.stem}.backup-schema{version}-{stamp}.db"
        )
        # Crear en exclusiva evita reemplazar un respaldo anterior por error.
        with backup_path.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(backup_path)) as backup:
                connection.backup(backup)
        except BaseException:
            backup_path.unlink(missing_ok=True)
            raise
        with db.transaction(connection):
            if db.schema_version(connection) != version:
                raise ValueError("database version changed during backup; stop all writers")
            for definition in definitions:
                existing = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ?", (definition["name"],)
                ).fetchone()
                if existing is not None:
                    if existing["sql"] != definition["sql"]:
                        raise ValueError(f"incompatible existing object: {definition['name']}")
                else:
                    connection.execute(definition["sql"])
            if "css_px_per_cm" not in calibration_columns:
                connection.execute("ALTER TABLE calibration ADD COLUMN css_px_per_cm REAL")
            connection.execute("UPDATE meta SET value = '8' WHERE key = 'schema_version'")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("database integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("database contains foreign key violations")
        return backup_path


def main(argv: list[str] | None = None) -> int:
    """Migra la base indicada y comunica dónde quedó el respaldo."""
    parser = argparse.ArgumentParser(description="Migra del esquema 7 al 8 con respaldo previo.")
    parser.add_argument("--db", type=Path, help="base existente; por defecto la configurada")
    parser.add_argument("--backup", type=Path, help="destino nuevo para el respaldo")
    args = parser.parse_args(argv)
    try:
        path = args.db if args.db is not None else load_config().database.path
        backup = migrate(path, args.backup)
        print(f"Migración completada. Respaldo: {backup}" if backup else "La base ya está al día.")
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
