"""Crea la base de datos del sistema a partir de ``server/schema.sql``.

Es idempotente: si la base ya existe con la versión de esquema esperada, no hace
nada; si existe con otra versión, falla y explica cómo recrearla. Uso::

    python -m scripts.init_db                 # base de config/shared.json
    python -m scripts.init_db --db otra.db    # otra ruta
    python -m scripts.init_db --reset         # borra y recrea (pide confirmación)
    python -m scripts.init_db --reset --yes   # borra y recrea sin preguntar
"""

import argparse
import sys
from contextlib import closing
from pathlib import Path
from typing import Literal

from shared import db
from shared.config import load_config

InitResult = Literal["created", "unchanged", "recreated"]
"""Qué hizo ``init_db``."""

_YES = {"s", "si", "sí", "y", "yes"}


def init_db(path: Path, *, reset: bool = False) -> InitResult:
    """Crea la base si no existe, o la recrea si se pide.

    Args:
        path: Archivo de la base de datos. Su carpeta se crea si falta.
        reset: Si es verdadero, borra la base existente y sus archivos WAL
            antes de crearla. Se pierden todos sus datos.

    Returns:
        ``"created"`` si no existía, ``"recreated"`` si se borró y se creó de
        nuevo, ``"unchanged"`` si ya existía con la versión esperada.

    Raises:
        SchemaVersionError: Si la base existe con otra versión del esquema y no
            se pidió ``reset``.
    """
    existed = path.exists()
    if existed and not reset:
        with closing(db.connect(path)) as connection:
            db.check_schema_version(connection)
        return "unchanged"
    if existed:
        delete_database(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(path, create=True)) as connection:
        db.create_schema(connection)
    return "recreated" if existed else "created"


def delete_database(path: Path) -> None:
    """Borra el archivo de la base y los auxiliares que crea el modo WAL.

    Args:
        path: Archivo de la base de datos.
    """
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si terminó bien, 1 si falló o se canceló.
    """
    parser = argparse.ArgumentParser(description="Crea la base de datos del sistema.")
    parser.add_argument(
        "--db", type=Path, help="ruta de la base (por defecto, database.path de la configuración)"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="borra la base y la crea de nuevo; se pierden los datos",
    )
    parser.add_argument("--yes", action="store_true", help="no pide confirmación con --reset")
    args = parser.parse_args(argv)

    path: Path = args.db or load_config().database.path
    if args.reset and path.exists() and not args.yes:
        answer = input(f"Se borrará {path} con todos sus datos. ¿Continuar? [s/N] ")
        if answer.strip().lower() not in _YES:
            print("Cancelado: no se borró nada.")
            return 1

    try:
        result = init_db(path, reset=args.reset)
    except db.SchemaVersionError as error:
        print(f"error: {path}: {error}", file=sys.stderr)
        return 1
    print(f"{result}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
