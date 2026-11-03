"""Integración I2: una sesión guiada completa en la app de prueba, con SUS.

Abre Chrome con la extensión (``browser/guided-session.mjs``), maneja el panel
real del evaluador y hace las 4 tareas del estudio de ejemplo en la tienda (V1)
como una persona: inicia sesión antes de la primera tarea, termina las tareas 1
a 3 con **Terminé**, recorre la tienda entre la 3 y la 4 y se rinde en la 4 con
**No pude**. Después contesta el SUS y cierra. Revisa la base que llenó el
servidor real:

- la sesión, sus tareas con la forma en que terminó cada una y el SUS;
- que cada evento lleva la tarea activa en su momento, y ninguna fuera de ellas;
- que cada ruta de la tienda registra su cambio de pantalla, incluidos ordenar,
  filtrar, el ancla de opiniones y la página de términos;
- que nada de lo escrito llega a la base y que la búsqueda queda redactada;
- que el análisis corre sobre la sesión real.

Es lenta y necesita Chrome y Node, así que solo corre con
``SUCA_BROWSER_TESTS=1``. El servidor escucha en la dirección de la
configuración, porque la extensión la tiene fija: si ya hay un servidor local
corriendo, hay que detenerlo antes.
"""

import dataclasses
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from collections.abc import Iterator
from contextlib import closing
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import load_parameters
from analysis.run import AnalysisResults, run_pipeline
from scripts.serve_test_app import create_server
from shared.config import ROOT_DIR
from shared.db import open_database

#: Guion que maneja Chrome.
DRIVER = ROOT_DIR / "tests" / "integration" / "browser" / "guided-session.mjs"

#: Variable que activa estas pruebas.
BROWSER_ENV = "SUCA_BROWSER_TESTS"

#: Tiempo máximo de la corrida de Chrome, en segundos.
RUN_TIMEOUT_S = 300

#: Versión de la tienda en la sesión: con problemas sembrados, como en el experimento.
VERSION = "V1"

#: Rutas en el orden en que se recorren, con los cambios de pantalla que debe
#: registrar la captura (``{n}`` es el número del pedido, distinto en cada corrida).
EXPECTED_SCREEN_CHANGES = [
    "/login",
    "/",
    "/search?q=redacted",  # tarea 1
    "/product/101",
    "/cart",  # tarea 2
    "/checkout/shipping",  # tarea 3
    "/checkout/payment",
    "/order/{n}/confirmation",
    "/",  # entre las tareas 3 y 4
    "/products",
    "/products?sort=price_asc",
    "/products?sort=price_asc&discount=1",
    "/search?q=redacted",
    "/product/104",
    "/product/104#resenas",
    "/terms.html",
    "/",
    "/account",  # tarea 4
]

#: Pantallas que el análisis debe ver: una por ruta de la tienda.
EXPECTED_ANALYSIS_SCREENS = {
    "/login",
    "/",
    "/search",
    "/product/{id}",
    "/cart",
    "/checkout/shipping",
    "/checkout/payment",
    "/order/{id}/confirmation",
    "/products",
    "/terms.html",
    "/account",
}

pytestmark = pytest.mark.skipif(
    os.environ.get(BROWSER_ENV) != "1", reason=f"set {BROWSER_ENV}=1 to run the browser tests"
)


@dataclasses.dataclass(frozen=True)
class Run:
    """Resultado de la corrida de Chrome.

    Attributes:
        summary: Lo que el guion dice que hizo (participante, respuestas del SUS…).
        database: Base que llenó el servidor.
        session_id: Sesión creada por el panel.
    """

    summary: dict[str, Any]
    database: Path
    session_id: int


@pytest.fixture(scope="module")
def app_url() -> Iterator[str]:
    """App de prueba, servida en un puerto libre."""
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def run(live_database: Path, app_url: str) -> Run:
    """Una sesión guiada completa en la tienda."""
    result = subprocess.run(
        [shutil.which("node") or "node", str(DRIVER), "--app-url", app_url, "--version", VERSION],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        cwd=ROOT_DIR,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["error"] is None, summary["error"]
    with closing(sqlite3.connect(live_database)) as connection:
        rows = connection.execute("SELECT id FROM session").fetchall()
    assert len(rows) == 1
    return Run(summary, live_database, rows[0][0])


def query(run: Run, sql: str) -> list[sqlite3.Row]:
    """Filas de una consulta sobre la base de la corrida, con la sesión como parámetro."""
    with closing(sqlite3.connect(run.database)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(sql, {"session_id": run.session_id}).fetchall()


def events(run: Run) -> list[dict[str, Any]]:
    """Eventos de la sesión, en orden, con sus columnas JSON leídas."""
    rows = query(run, "SELECT * FROM event WHERE session_id = :session_id ORDER BY t, id")
    return [
        {**dict(row), **{key: json.loads(row[key]) if row[key] else None
                         for key in ("screen", "element", "data")}}
        for row in rows
    ]  # fmt: skip


def path_of(url: str) -> str:
    """Ruta de una dirección de la tienda, con su consulta y su fragmento."""
    return re.sub(r"^https?://[^/]+", "", url)


@pytest.fixture(scope="module")
def analysis(run: Run) -> AnalysisResults:
    """Análisis de la sesión, sin guardar resultados."""
    connection = open_database(run.database)
    try:
        data = SqliteAnalysisRepository(connection).load_session(run.session_id)
    finally:
        connection.close()
    return run_pipeline(data, load_parameters())


def test_the_panel_creates_a_closed_guided_session(run: Run) -> None:
    (session,) = query(run, "SELECT * FROM session WHERE id = :session_id")

    assert session["mode"] == "guided"
    assert session["version"] == VERSION
    assert session["participant_id"] == run.summary["participant_id"]
    assert session["ended_at"] is not None
    assert run.summary["page_problems"] == []
    assert run.summary["panel_problems"] == []
    assert [problem for problem in run.summary["worker_problems"] if "dropped" in problem] == []


def test_each_task_is_recorded_with_how_it_ended(run: Run) -> None:
    """Las 4 tareas, en el orden del estudio, una tras otra y sin solaparse."""
    rows = query(
        run,
        """SELECT task.position, session_task.t_start, session_task.t_end, session_task.ended_by
           FROM session_task JOIN task ON task.id = session_task.task_id
           WHERE session_task.session_id = :session_id
           ORDER BY session_task.t_start""",
    )

    assert [row["position"] for row in rows] == [1, 2, 3, 4]
    assert [row["ended_by"] for row in rows] == run.summary["tasks"]
    assert all(row["t_start"] < row["t_end"] for row in rows)
    assert all(before["t_end"] < after["t_start"] for before, after in pairwise(rows))


def test_the_sus_is_stored_with_its_score(run: Run) -> None:
    """El servidor calcula el puntaje: (impares − 1) + (5 − pares), por 2,5."""
    (row,) = query(run, "SELECT answers, score FROM sus_response WHERE session_id = :session_id")
    answers = run.summary["sus_answers"]
    expected = 2.5 * sum(
        answer - 1 if item % 2 == 1 else 5 - answer for item, answer in enumerate(answers, start=1)
    )

    assert json.loads(row["answers"]) == answers
    assert row["score"] == pytest.approx(expected)


def test_events_carry_the_task_that_was_active(run: Run) -> None:
    """Dentro de una tarea, su ``task_id``; antes, entre tareas y después, ninguno."""
    tasks = query(
        run, "SELECT task_id, t_start, t_end FROM session_task WHERE session_id = :session_id"
    )
    recorded = [event for event in events(run) if event["type"] != "camera_gap"]

    def active_at(t: float) -> int | None:
        return next(
            (task["task_id"] for task in tasks if task["t_start"] <= t <= task["t_end"]), None
        )

    wrong = [
        (event["type"], event["task_id"], active_at(event["t"]))
        for event in recorded
        if event["task_id"] != active_at(event["t"])
    ]
    assert wrong == []
    assert {event["task_id"] for event in recorded} == {None} | {task["task_id"] for task in tasks}


def test_every_route_records_its_screen_change(run: Run) -> None:
    """Rutas de la aplicación, ordenar y filtrar, el ancla, otra página y el regreso."""
    changes = [
        re.sub(r"/order/\d+/", "/order/{n}/", path_of(event["screen"]["url"]))
        for event in events(run)
        if event["type"] == "screen_change"
    ]

    assert changes == EXPECTED_SCREEN_CHANGES


def test_nothing_typed_reaches_the_database(run: Run) -> None:
    """Lo escrito en el boletín lleva un prefijo que la tienda no muestra."""
    sentinel = run.summary["sentinel"].lower()
    for file in run.database.parent.glob(f"{run.database.name}*"):
        assert sentinel.encode() not in file.read_bytes().lower(), file.name
    fields = [event for event in events(run) if event["type"] in {"focus_in", "field_change"}]

    assert fields
    assert all(event["element"]["text"] is None for event in fields)


def test_the_search_is_redacted(run: Run) -> None:
    searches = [event["screen"] for event in events(run) if "/search" in event["screen"]["url"]]

    assert searches
    assert all(
        path_of(screen["url"]) == "/search?q=redacted" and screen["title"] == ""
        for screen in searches
    )


def test_the_analysis_runs_on_the_real_session(analysis: AnalysisResults) -> None:
    """Las 7 etapas corren y hay un resultado por tarea."""
    assert sorted(analysis.task_results["task_id"].tolist()) == [1, 2, 3, 4]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "events recorded right after a route change carry the previous title, and "
        "assign_screens adds the title to every URL with more than one: one route "
        "becomes several screens"
    ),
)
def test_the_analysis_sees_one_screen_per_route(analysis: AnalysisResults) -> None:
    """Ordenar, filtrar y el ancla de opiniones no crean pantallas nuevas."""
    screens = set(analysis.data.events["screen"])

    assert screens == EXPECTED_ANALYSIS_SCREENS
