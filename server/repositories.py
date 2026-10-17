"""Acceso a la base de datos del servidor.

Las interfaces (``Protocol``) son pequeñas y por necesidad: cada función de
``services`` pide solo la que usa, y una prueba puede sustituirla por otra
implementación. ``SqliteRepository`` las implementa todas sobre una conexión y
es el único lugar del servidor con SQL.

Los campos JSON se guardan como texto: quien escribe filas con ``insert`` o
``upsert`` ya los entrega serializados.
"""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from shared import db


@dataclass(frozen=True)
class SessionInfo:
    """Lo que el servidor necesita saber de una sesión para aceptar datos.

    Attributes:
        id: Identificador de la sesión.
        study_id: Estudio de la sesión.
        mode: Modo de la sesión (``session_mode``).
        ended_at: Momento del cierre, o ``None`` si sigue abierta.
    """

    id: int
    study_id: int
    mode: str
    ended_at: float | None


class StudyReader(Protocol):
    """Lectura de estudios, tareas y referencias."""

    def list_studies(self) -> list[dict[str, Any]]:
        """Devuelve todos los estudios, ordenados por id."""
        ...

    def study_exists(self, study_id: int) -> bool:
        """Indica si existe un estudio."""
        ...

    def list_tasks(self, study_id: int) -> list[dict[str, Any]]:
        """Devuelve las tareas de un estudio en orden de posición."""
        ...

    def list_references(self, study_id: int, status: str) -> list[dict[str, Any]]:
        """Devuelve las referencias de un estudio con un estado.

        ``end_condition`` se devuelve ya decodificada.
        """
        ...

    def task_ids(self, study_id: int) -> set[int]:
        """Devuelve los identificadores de las tareas de un estudio."""
        ...


class SessionStore(Protocol):
    """Creación, consulta y cierre de sesiones, y respuestas del SUS."""

    def get_session(self, session_id: int) -> SessionInfo | None:
        """Devuelve una sesión, o ``None`` si no existe."""
        ...

    def create_session(
        self,
        *,
        study_id: int,
        participant_id: str,
        version: str,
        mode: str,
        started_at: float,
        screen_info: Mapping[str, Any],
    ) -> int:
        """Crea una sesión (y su participante si no existe) y devuelve su id."""
        ...

    def close_session(self, session_id: int, ended_at: float) -> None:
        """Marca una sesión como cerrada."""
        ...

    def save_sus(self, session_id: int, answers: Sequence[int], score: float) -> None:
        """Guarda o reemplaza las respuestas del SUS de una sesión."""
        ...


class BatchWriter(Protocol):
    """Escritura de los registros de un lote en sus tablas."""

    def transaction(self) -> AbstractContextManager[object]:
        """Abre una transacción: lo escrito dentro se guarda todo o nada."""
        ...

    def insert(self, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
        """Inserta filas en una tabla. Todas las filas tienen las mismas columnas."""
        ...

    def upsert(self, table: str, rows: Sequence[Mapping[str, Any]], key: Sequence[str]) -> None:
        """Inserta filas o, si ya existe una con la misma clave, la reemplaza."""
        ...

    def update_session(self, session_id: int, values: Mapping[str, Any]) -> None:
        """Actualiza columnas de una sesión."""
        ...


class ReferenceStore(Protocol):
    """Creación de referencias."""

    def create_draft_reference(self, *, task_id: int, source_session_id: int, status: str) -> int:
        """Crea una referencia vacía, o devuelve la existente para esa tarea y sesión."""
        ...


class CaptureStore(Protocol):
    """Registro de capturas de pantalla."""

    def add_capture(
        self, *, study_id: int, screen: Mapping[str, Any], file_path: str, t: float
    ) -> int:
        """Registra una captura ya guardada en disco y devuelve su id."""
        ...


class Repository(StudyReader, SessionStore, BatchWriter, ReferenceStore, CaptureStore, Protocol):
    """Todo lo que ofrece el repositorio del servidor.

    Solo lo usan los endpoints, para entregar a cada servicio la interfaz que
    necesita.
    """


class SqliteRepository:
    """Implementación de todas las interfaces del servidor sobre SQLite.

    Attributes:
        connection: Conexión abierta con ``shared.db``. Quien crea el
            repositorio la cierra.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Crea el repositorio sobre una conexión.

        Args:
            connection: Conexión abierta con ``shared.db``.
        """
        self.connection = connection

    # --- Estudios ---------------------------------------------------------

    def list_studies(self) -> list[dict[str, Any]]:
        """Devuelve todos los estudios, ordenados por id."""
        rows = self.connection.execute(
            "SELECT id, name, system_under_test, description FROM study ORDER BY id"
        )
        return [dict(row) for row in rows]

    def study_exists(self, study_id: int) -> bool:
        """Indica si existe un estudio."""
        row = self.connection.execute("SELECT 1 FROM study WHERE id = ?", (study_id,)).fetchone()
        return row is not None

    def list_tasks(self, study_id: int) -> list[dict[str, Any]]:
        """Devuelve las tareas de un estudio en orden de posición."""
        rows = self.connection.execute(
            "SELECT id, position, instruction FROM task WHERE study_id = ? ORDER BY position",
            (study_id,),
        )
        return [dict(row) for row in rows]

    def list_references(self, study_id: int, status: str) -> list[dict[str, Any]]:
        """Devuelve las referencias de un estudio con un estado.

        ``end_condition`` se devuelve ya decodificada.
        """
        rows = self.connection.execute(
            """
            SELECT reference.id, reference.task_id, reference.end_condition
            FROM reference JOIN task ON task.id = reference.task_id
            WHERE task.study_id = ? AND reference.status = ?
            ORDER BY task.position, reference.id
            """,
            (study_id, status),
        )
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "end_condition": _from_json(row["end_condition"]),
            }
            for row in rows
        ]

    def task_ids(self, study_id: int) -> set[int]:
        """Devuelve los identificadores de las tareas de un estudio."""
        rows = self.connection.execute("SELECT id FROM task WHERE study_id = ?", (study_id,))
        return {row["id"] for row in rows}

    # --- Sesiones ---------------------------------------------------------

    def get_session(self, session_id: int) -> SessionInfo | None:
        """Devuelve una sesión, o ``None`` si no existe."""
        row = self.connection.execute(
            "SELECT id, study_id, mode, ended_at FROM session WHERE id = ?", (session_id,)
        ).fetchone()
        return None if row is None else SessionInfo(**dict(row))

    def create_session(
        self,
        *,
        study_id: int,
        participant_id: str,
        version: str,
        mode: str,
        started_at: float,
        screen_info: Mapping[str, Any],
    ) -> int:
        """Crea una sesión (y su participante si no existe) y devuelve su id."""
        with db.transaction(self.connection):
            # Un participante puede tener varias sesiones (por ejemplo, guiada y libre).
            self.connection.execute(
                "INSERT INTO participant (id) VALUES (?) ON CONFLICT (id) DO NOTHING",
                (participant_id,),
            )
            cursor = self.connection.execute(
                """
                INSERT INTO session
                    (study_id, participant_id, version, mode, started_at, screen_info)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (study_id, participant_id, version, mode, started_at, _to_json(screen_info)),
            )
        return cursor.lastrowid

    def close_session(self, session_id: int, ended_at: float) -> None:
        """Marca una sesión como cerrada."""
        self.connection.execute(
            "UPDATE session SET ended_at = ? WHERE id = ?", (ended_at, session_id)
        )

    def save_sus(self, session_id: int, answers: Sequence[int], score: float) -> None:
        """Guarda o reemplaza las respuestas del SUS de una sesión."""
        self.connection.execute(
            """
            INSERT INTO sus_response (session_id, answers, score) VALUES (?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE
                SET answers = excluded.answers, score = excluded.score
            """,
            (session_id, _to_json(list(answers)), score),
        )

    # --- Lotes ------------------------------------------------------------

    def transaction(self) -> AbstractContextManager[object]:
        """Abre una transacción: lo escrito dentro se guarda todo o nada."""
        return db.transaction(self.connection)

    def insert(self, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
        """Inserta filas en una tabla. Todas las filas tienen las mismas columnas.

        Los nombres de tabla y columna vienen del código de los manejadores,
        nunca de la petición.
        """
        if not rows:
            return
        columns = list(rows[0])
        self.connection.executemany(
            f"INSERT INTO {_quote(table)} ({_column_list(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            [tuple(row[column] for column in columns) for row in rows],
        )

    def upsert(self, table: str, rows: Sequence[Mapping[str, Any]], key: Sequence[str]) -> None:
        """Inserta filas o, si ya existe una con la misma clave, la reemplaza."""
        if not rows:
            return
        columns = list(rows[0])
        updates = ", ".join(
            f"{_quote(column)} = excluded.{_quote(column)}"
            for column in columns
            if column not in key
        )
        self.connection.executemany(
            f"INSERT INTO {_quote(table)} ({_column_list(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT ({_column_list(key)}) DO UPDATE SET {updates}",
            [tuple(row[column] for column in columns) for row in rows],
        )

    def update_session(self, session_id: int, values: Mapping[str, Any]) -> None:
        """Actualiza columnas de una sesión."""
        if not values:
            return
        assignments = ", ".join(f"{_quote(column)} = ?" for column in values)
        self.connection.execute(
            f"UPDATE session SET {assignments} WHERE id = ?", (*values.values(), session_id)
        )

    # --- Referencias y capturas -------------------------------------------

    def create_draft_reference(self, *, task_id: int, source_session_id: int, status: str) -> int:
        """Crea una referencia vacía, o devuelve la existente para esa tarea y sesión."""
        self.connection.execute(
            """
            INSERT INTO reference (
                task_id, source_session_id, steps, candidates, end_condition, required_steps,
                status
            )
            VALUES (?, ?, '[]', '[]', NULL, '[]', ?)
            ON CONFLICT (task_id, source_session_id) DO NOTHING
            """,
            (task_id, source_session_id, status),
        )
        row = self.connection.execute(
            "SELECT id FROM reference WHERE task_id = ? AND source_session_id = ?",
            (task_id, source_session_id),
        ).fetchone()
        return row["id"]

    def add_capture(
        self, *, study_id: int, screen: Mapping[str, Any], file_path: str, t: float
    ) -> int:
        """Registra una captura ya guardada en disco y devuelve su id."""
        cursor = self.connection.execute(
            "INSERT INTO screen_capture (study_id, screen, file_path, t) VALUES (?, ?, ?, ?)",
            (study_id, _to_json(screen), file_path, t),
        )
        return cursor.lastrowid


def _quote(name: str) -> str:
    """Escribe un nombre de tabla o columna entre comillas dobles.

    Hace falta, por ejemplo, para la columna ``"values"``, palabra reservada.

    Args:
        name: Nombre tal como está en el esquema.

    Returns:
        Nombre entre comillas, listo para SQL.
    """
    return '"' + name.replace('"', '""') + '"'


def _column_list(columns: Sequence[str]) -> str:
    """Une nombres de columna entre comillas, separados por comas."""
    return ", ".join(_quote(column) for column in columns)


def _to_json(value: Any) -> str:
    """Serializa un valor para una columna JSON."""
    return json.dumps(value, ensure_ascii=False)


def _from_json(text: str | None) -> Any:
    """Decodifica una columna JSON; ``NULL`` se devuelve como ``None``."""
    return None if text is None else json.loads(text)
