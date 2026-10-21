"""Acceso a la base de datos SQLite.

Reúne lo que necesita cualquier parte del sistema que abra la base: una fábrica
de conexiones configuradas igual en todos lados, un manejador de transacciones
y el control de la versión del esquema (``server/schema.sql``).

Las conexiones se cierran con ``contextlib.closing``: el ``with`` propio de
``sqlite3.Connection`` no cierra la conexión, solo confirma o deshace.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from functools import cache
from pathlib import Path

from shared.config import ROOT_DIR

SCHEMA_PATH = ROOT_DIR / "server" / "schema.sql"
"""Definición de todas las tablas."""

BUSY_TIMEOUT_S = 5.0
"""Segundos que una conexión espera si otra tiene la base bloqueada para escribir."""


class SchemaVersionError(RuntimeError):
    """La base de datos tiene otra versión del esquema, o no tiene ninguna."""


def connect(
    path: Path | str, *, create: bool = False, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Abre una conexión configurada para el sistema.

    La conexión usa modo WAL (lectores y un escritor a la vez), claves foráneas
    activas, filas accesibles por nombre de columna y espera ante bloqueo. Está
    en modo autocommit: las escrituras de varias sentencias van en
    ``transaction``.

    Args:
        path: Archivo de la base de datos.
        create: Si es verdadero, crea el archivo si no existe. Por defecto un
            archivo inexistente es un error, para no crear una base vacía por
            una ruta mal escrita.
        check_same_thread: Si es falso, la conexión puede usarse desde otro
            hilo que el que la creó. Lo necesita el servidor, porque FastAPI
            abre, usa y cierra la conexión de una petición en hilos distintos.
            Es seguro solo si la conexión no se usa desde dos hilos a la vez.

    Returns:
        Conexión abierta. Quien la abre la cierra.

    Raises:
        FileNotFoundError: Si el archivo no existe y ``create`` es falso.
    """
    path = Path(path)
    if not create and not path.is_file():
        raise FileNotFoundError(
            f"database not found: {path}; create it with: python -m scripts.init_db"
        )
    mode = "rwc" if create else "rw"
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode={mode}",
        uri=True,
        timeout=BUSY_TIMEOUT_S,
        isolation_level=None,
        check_same_thread=check_same_thread,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    # Con WAL, NORMAL solo arriesga la última transacción ante un corte de luz,
    # no la integridad de la base, y escribe mucho más rápido.
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def open_database(path: Path | str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Abre una base de datos existente y comprueba la versión de su esquema.

    Es la forma de abrir la base para el servidor, el análisis, el panel y los
    scripts que no la crean.

    Args:
        path: Archivo de la base de datos.
        check_same_thread: Igual que en ``connect``.

    Returns:
        Conexión abierta.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        SchemaVersionError: Si la versión del esquema no es la esperada.
    """
    connection = connect(path, check_same_thread=check_same_thread)
    try:
        check_schema_version(connection)
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Agrupa varias sentencias en una transacción: se guardan todas o ninguna.

    Toma el bloqueo de escritura al empezar (``BEGIN IMMEDIATE``), para que dos
    escritores no choquen a mitad de la transacción.

    Args:
        connection: Conexión creada con ``connect``.

    Yields:
        La misma conexión.

    Raises:
        RuntimeError: Si ya hay una transacción abierta en la conexión.
    """
    if connection.in_transaction:
        raise RuntimeError("nested transactions are not supported")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        # Algunos errores de SQLite ya deshacen la transacción por su cuenta.
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def create_schema(connection: sqlite3.Connection) -> None:
    """Crea todas las tablas en una base vacía, en una sola transacción.

    Args:
        connection: Conexión a una base sin tablas.

    Raises:
        sqlite3.Error: Si alguna sentencia falla; no queda nada creado.
    """
    script = SCHEMA_PATH.read_text(encoding="utf-8")
    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{script}\nCOMMIT;")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def schema_version(connection: sqlite3.Connection) -> str | None:
    """Lee la versión del esquema de una base.

    Args:
        connection: Conexión abierta.

    Returns:
        Versión guardada en ``meta``, o ``None`` si la base no tiene esa tabla
        o esa clave (no es una base del sistema).
    """
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else row[0]


@cache
def expected_schema_version() -> str:
    """Devuelve la versión del esquema que define ``server/schema.sql``.

    Se obtiene ejecutando el esquema en una base en memoria, para que la versión
    esté escrita en un solo lugar.

    Returns:
        Versión del esquema.
    """
    with closing(sqlite3.connect(":memory:")) as memory:
        memory.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        version = schema_version(memory)
    if version is None:
        raise RuntimeError(f"{SCHEMA_PATH} does not set meta.schema_version")
    return version


def check_schema_version(connection: sqlite3.Connection) -> None:
    """Comprueba que la base tenga la versión del esquema esperada.

    Args:
        connection: Conexión abierta.

    Raises:
        SchemaVersionError: Si la versión no coincide o la base no tiene versión.
    """
    found = schema_version(connection)
    expected = expected_schema_version()
    if found != expected:
        raise SchemaVersionError(
            f"database schema version is {found!r}, expected {expected!r}; "
            "recreate it with: python -m scripts.init_db --reset (deletes its data)"
        )
