"""Carga o actualiza un estudio y sus tareas desde un archivo YAML.

El archivo se valida contra ``contracts/study.schema.json`` antes de tocar la
base. El nombre identifica al estudio y la posición identifica a cada tarea, así
que volver a cargar el mismo archivo no duplica nada y conserva los id. Todo se
aplica en una transacción: si algo falla, la base queda como estaba. Uso::

    python -m scripts.load_study studies/example.yaml
    python -m scripts.load_study studies/example.yaml --db otra.db
"""

import argparse
import sqlite3
import sys
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shared import contracts, db
from shared.config import load_config


class StudyFileError(ValueError):
    """El archivo del estudio no se puede leer, no cumple el contrato o no se puede aplicar."""


@dataclass(frozen=True)
class LoadedStudy:
    """Resultado de cargar un estudio.

    Attributes:
        study_id: Identificador del estudio en la base.
        task_ids: Identificadores de sus tareas, en orden de posición.
    """

    study_id: int
    task_ids: tuple[int, ...]


def read_study(path: Path) -> dict[str, Any]:
    """Lee y valida un archivo de estudio.

    Args:
        path: Archivo YAML.

    Returns:
        Estudio que cumple ``contracts/study.schema.json``.

    Raises:
        StudyFileError: Si el archivo no existe, no es YAML válido o no cumple
            el contrato. El mensaje lista cada error con la ruta del campo.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise StudyFileError(f"{path}: cannot read file: {error}") from None
    except yaml.YAMLError as error:
        raise StudyFileError(f"{path}: invalid YAML: {error}") from None
    errors = contracts.validate("study", document)
    if errors:
        details = "\n".join(f"  {error}" for error in errors)
        raise StudyFileError(f"{path}: invalid study:\n{details}")
    return document


def load_study(connection: sqlite3.Connection, study: Mapping[str, Any]) -> LoadedStudy:
    """Inserta o actualiza un estudio y sus tareas.

    Las tareas que el archivo ya no tiene se borran, salvo que tengan datos
    grabados o referencias: en ese caso no se aplica ningún cambio.

    Args:
        connection: Conexión a una base con el esquema esperado.
        study: Estudio ya validado con ``read_study``.

    Returns:
        Identificadores del estudio y de sus tareas.

    Raises:
        StudyFileError: Si habría que borrar una tarea con datos o referencias.
    """
    name = study["name"]
    tasks = study["tasks"]
    with db.transaction(connection):
        connection.execute(
            """
            INSERT INTO study (name, system_under_test, description) VALUES (?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET
                system_under_test = excluded.system_under_test,
                description = excluded.description
            """,
            (name, study["system_under_test"], study.get("description")),
        )
        study_id = connection.execute("SELECT id FROM study WHERE name = ?", (name,)).fetchone()[0]
        connection.executemany(
            """
            INSERT INTO task (study_id, position, instruction) VALUES (?, ?, ?)
            ON CONFLICT (study_id, position) DO UPDATE SET instruction = excluded.instruction
            """,
            [
                (study_id, position, task["instruction"])
                for position, task in enumerate(tasks, start=1)
            ],
        )
        try:
            connection.execute(
                "DELETE FROM task WHERE study_id = ? AND position > ?", (study_id, len(tasks))
            )
        except sqlite3.IntegrityError:
            raise StudyFileError(
                f"study {name!r}: cannot remove tasks after position {len(tasks)} "
                "because they have recorded data or references"
            ) from None
        task_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT id FROM task WHERE study_id = ? ORDER BY position", (study_id,)
            )
        )
    return LoadedStudy(study_id=study_id, task_ids=task_ids)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se cargó, 1 si falló.
    """
    parser = argparse.ArgumentParser(description="Carga o actualiza un estudio desde YAML.")
    parser.add_argument("study", type=Path, help="archivo YAML del estudio")
    parser.add_argument(
        "--db", type=Path, help="ruta de la base (por defecto, database.path de la configuración)"
    )
    args = parser.parse_args(argv)

    path: Path = args.db or load_config().database.path
    try:
        study = read_study(args.study)
        with closing(db.open_database(path)) as connection:
            loaded = load_study(connection, study)
    except (StudyFileError, FileNotFoundError, db.SchemaVersionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"loaded study {study['name']!r} (id {loaded.study_id}) "
        f"with {len(loaded.task_ids)} tasks into {path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
