"""Fixtures de las pruebas del análisis.

``analysis_db`` crea una base pequeña con:

- el estudio 1 (tareas 1 y 2) y el estudio 2 (tarea 3);
- la sesión 1: guiada y cerrada, con eventos (insertados fuera de orden),
  mirada, rostro, una calibración, una tarea y referencias confirmadas y en
  borrador;
- la sesión 2: libre y todavía abierta, con un clic.

La tarea 3 del estudio 2 tiene una referencia confirmada que no debe aparecer
en las sesiones del estudio 1.
"""

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

import pytest

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import Parameters, load_parameters
from shared import db

T0 = 1_791_380_000_000.0
"""Inicio de la sesión 1, en ms desde 1970."""

BUTTON = {
    "tag": "button",
    "id": "pay",
    "role": "button",
    "text": "Ir a pagar",
    "selector": "#pay",
    "box": {"x": 10, "y": 20, "w": 100, "h": 30},
    "interactive": True,
}


def _screen(url: str, title: str) -> str:
    return json.dumps({"url": url, "title": title})


def _fill(connection: sqlite3.Connection) -> None:
    """Inserta los datos de la base pequeña."""
    execute = connection.execute
    execute("INSERT INTO study (id, name, system_under_test) VALUES (1, 'Estudio 1', 'App')")
    execute("INSERT INTO study (id, name, system_under_test) VALUES (2, 'Estudio 2', 'App')")
    execute("INSERT INTO task (id, study_id, position, instruction) VALUES (1, 1, 1, 'Tarea uno')")
    execute("INSERT INTO task (id, study_id, position, instruction) VALUES (2, 1, 2, 'Tarea dos')")
    execute("INSERT INTO task (id, study_id, position, instruction) VALUES (3, 2, 1, 'Otra')")
    execute("INSERT INTO participant (id) VALUES ('P01'), ('P02')")
    execute(
        "INSERT INTO session (id, study_id, participant_id, version, mode, started_at, ended_at,"
        " screen_info) VALUES (1, 1, 'P01', 'V0', 'guided', ?, ?, ?)",
        (T0, T0 + 60_000, json.dumps({"window_width": 1280, "window_height": 800})),
    )
    execute(
        "INSERT INTO session (id, study_id, participant_id, version, mode, started_at)"
        " VALUES (2, 1, 'P02', 'V1', 'free', ?)",
        (T0 + 100_000,),
    )
    events = [
        # Insertados fuera de orden: el repositorio los entrega por tiempo.
        (
            1,
            T0 + 1000,
            "click",
            50,
            30,
            _screen("https://shop.local/cart/8812", "Carrito"),
            1,
            json.dumps(BUTTON),
            None,
        ),
        (
            1,
            T0 + 500,
            "mousemove",
            40,
            25,
            _screen("https://shop.local/cart/8812", "Carrito"),
            None,
            None,
            None,
        ),
        (
            1,
            T0 + 2000,
            "screen_change",
            None,
            None,
            _screen("https://shop.local/order/1", "Pedido"),
            1,
            None,
            json.dumps({}),
        ),
        (
            2,
            T0 + 101_000,
            "click",
            5,
            5,
            _screen("https://shop.local/", "Inicio"),
            None,
            json.dumps(BUTTON),
            None,
        ),
    ]
    connection.executemany(
        "INSERT INTO event (session_id, t, type, x, y, screen, task_id, element, data)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        events,
    )
    connection.executemany(
        "INSERT INTO gaze_sample (session_id, t, x, y, scroll_x, scroll_y, element_selector, zone,"
        " valid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, T0 + 600, 41, 26, 0, 0, "#pay", "main", 1),
            (1, T0 + 633, None, None, 0, 0, None, None, 0),
        ],
    )
    execute(
        'INSERT INTO face_sample (session_id, t, "values", head_yaw, head_pitch, face_detected)'
        " VALUES (1, ?, ?, 1.5, -2.0, 1)",
        (T0 + 700, json.dumps({"smile": 0.2})),
    )
    execute(
        "INSERT INTO calibration (session_id, t, type, error_px, error_deg, accepted)"
        " VALUES (1, ?, 'initial', 80, 2.1, 1)",
        (T0 + 100,),
    )
    execute(
        "INSERT INTO session_task (session_id, task_id, t_start, t_end, ended_by)"
        " VALUES (1, 1, ?, ?, 'reference')",
        (T0 + 900, T0 + 30_000),
    )
    references = [
        (1, 1, "confirmed", json.dumps({"type": "visible_text", "text": "Pedido confirmado"})),
        (2, 2, "draft", None),
        (3, 3, "confirmed", json.dumps({"type": "url_pattern", "pattern": "/done"})),
    ]
    connection.executemany(
        "INSERT INTO reference (id, task_id, steps, candidates, end_condition, required_steps,"
        " status, duration_ms) VALUES (?, ?, '[]', '[]', ?, '[0]', ?, 25000)",
        [(ref_id, task_id, end, status) for ref_id, task_id, status, end in references],
    )


@pytest.fixture
def analysis_db(tmp_path: Path) -> Path:
    """Base pequeña con el esquema actual y los datos descritos arriba."""
    path = tmp_path / "analysis.db"
    with closing(db.connect(path, create=True)) as connection:
        db.create_schema(connection)
        with db.transaction(connection):
            _fill(connection)
    return path


@pytest.fixture
def connection(analysis_db: Path) -> Iterator[sqlite3.Connection]:
    """Conexión abierta a la base pequeña."""
    with closing(db.open_database(analysis_db)) as opened:
        yield opened


@pytest.fixture
def repository(connection: sqlite3.Connection) -> SqliteAnalysisRepository:
    """Repositorio del análisis sobre la base pequeña."""
    return SqliteAnalysisRepository(connection)


@pytest.fixture
def params() -> Parameters:
    """Parámetros por defecto."""
    return load_parameters()


@pytest.fixture
def count_rows(connection: sqlite3.Connection) -> Callable[[str], int]:
    """Devuelve una función que cuenta las filas de una tabla."""
    return lambda table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
