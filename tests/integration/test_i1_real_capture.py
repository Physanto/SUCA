"""Integración I1: la captura real llega completa, válida y sin lo escrito.

Abre Chrome con la extensión (``browser/real-capture.mjs``), hace sesiones en
modo libre como una persona y revisa la base que llenó el servidor real:

- en la página de prueba, que llegan todos los tipos de evento de la captura;
- en sitios reales, que llegan los eventos de uso común y que la búsqueda queda
  redactada en la dirección;
- en todas, que nada de lo escrito en los campos está en la base, y que el
  worker no descartó ningún lote (el servidor rechaza los que no cumplen el
  contrato, así que un lote aceptado es un lote válido).

Son pruebas lentas y necesitan Chrome y Node, así que solo corren si se pide:

- ``SUCA_BROWSER_TESTS=1``: la página de prueba, servida en la propia computadora.
- ``SUCA_EXTERNAL_SITES=1`` (además): dos sitios reales; necesita internet.

El servidor escucha en la dirección de la configuración, porque la extensión
la tiene fija: si ya hay un servidor local corriendo, hay que detenerlo antes.
"""

import dataclasses
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from scripts.serve_test_page import create_server
from scripts.simulation import store
from server.app import create_app
from shared import contracts
from shared.config import ROOT_DIR, load_config

#: Guion que maneja Chrome.
DRIVER = ROOT_DIR / "tests" / "integration" / "browser" / "real-capture.mjs"

#: Variables que activan estas pruebas.
BROWSER_ENV = "SUCA_BROWSER_TESTS"
EXTERNAL_ENV = "SUCA_EXTERNAL_SITES"

#: Tiempo máximo de una corrida de Chrome, en segundos.
RUN_TIMEOUT_S = 300

#: Tipos de evento que produce la captura; ``camera_gap`` lo produce la cámara.
CAPTURE_EVENT_TYPES = frozenset(contracts.enums()["event_type"]) - {"camera_gap"}

#: Eventos que una visita normal a un sitio real siempre produce.
COMMON_EVENT_TYPES = frozenset(
    {"screen_change", "mousemove", "scroll", "click", "click_response", "selection",
     "focus_in", "field_change"}
)  # fmt: skip

pytestmark = pytest.mark.skipif(
    os.environ.get(BROWSER_ENV) != "1", reason=f"set {BROWSER_ENV}=1 to run the browser tests"
)


@dataclasses.dataclass(frozen=True)
class Run:
    """Resultado de una corrida de Chrome.

    Attributes:
        sessions: Resumen de cada sesión, por sitio (``session_id``, ``error``…).
        sentinel: Prefijo de todo lo que se escribió en los campos.
        worker_problems: Errores y avisos de la consola del service worker.
        database: Base que llenó el servidor.
    """

    sessions: dict[str, dict[str, Any]]
    sentinel: str
    worker_problems: list[str]
    database: Path


def _port_is_free(host: str, port: int) -> bool:
    """Indica si nadie escucha en el puerto."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        return probe.connect_ex((host, port)) != 0


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Servidor real con una base nueva, en la dirección que usa la extensión."""
    import uvicorn

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    config = load_config()
    host, port = config.server.host, config.server.port
    if not _port_is_free(host, port):
        pytest.fail(f"something is already listening on {host}:{port}; stop the local server")
    path = tmp_path_factory.mktemp("i1") / "suca.db"
    store.create_database(path).close()
    config = dataclasses.replace(config, database=dataclasses.replace(config.database, path=path))
    server = uvicorn.Server(
        uvicorn.Config(create_app(config), host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            pytest.fail("the local server did not start")
        time.sleep(0.05)
    yield path
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def test_page_url() -> Iterator[str]:
    """Página de prueba de la extensión, servida en un puerto libre."""
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def run_chrome(database: Path, *args: str) -> Run:
    """Corre el guion de Chrome con los argumentos dados y devuelve su resumen."""
    result = subprocess.run(
        [shutil.which("node") or "node", str(DRIVER), *args],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        cwd=ROOT_DIR,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    sessions = {session["site"]: session for session in output["sessions"]}
    for session in sessions.values():
        assert session["error"] is None, session["error"]
        assert "capture" in session["started"], session
        assert session["failed"] == [], session
    return Run(sessions, output["sentinel"], output["worker_problems"], database)


@pytest.fixture(scope="module")
def test_page_run(database: Path, test_page_url: str) -> Run:
    """Una sesión en la página de prueba."""
    return run_chrome(database, "--site", "test_page", "--test-page-url", test_page_url)


@pytest.fixture(scope="module")
def external_run(database: Path) -> Run:
    """Una sesión en cada sitio real."""
    if os.environ.get(EXTERNAL_ENV) != "1":
        pytest.skip(f"set {EXTERNAL_ENV}=1 to run the external sites")
    return run_chrome(database, "--site", "python_docs", "--site", "react")


def events(run: Run, site: str) -> list[dict[str, Any]]:
    """Eventos de la sesión de un sitio, en orden, con sus columnas JSON leídas."""
    with closing(sqlite3.connect(run.database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM event WHERE session_id = ? ORDER BY t, id",
            (run.sessions[site]["session_id"],),
        ).fetchall()
    return [
        {**dict(row), **{key: json.loads(row[key]) if row[key] else None
                         for key in ("screen", "element", "data")}}
        for row in rows
    ]  # fmt: skip


def assert_nothing_typed_is_stored(run: Run) -> None:
    """Nada de lo escrito está en la base: ni en sus archivos ni en su volcado de texto."""
    sentinel = run.sentinel.lower()
    for file in run.database.parent.glob(f"{run.database.name}*"):
        assert sentinel.encode() not in file.read_bytes().lower(), file.name
    with closing(sqlite3.connect(run.database)) as connection:
        dump = "\n".join(connection.iterdump()).lower()
    assert sentinel not in dump


def assert_no_batch_was_dropped(run: Run) -> None:
    """El worker no descartó lotes: el servidor los aceptó todos."""
    assert [problem for problem in run.worker_problems if "dropped" in problem] == []


def assert_session_closed(run: Run, site: str) -> None:
    """La sesión quedó cerrada en el servidor."""
    with closing(sqlite3.connect(run.database)) as connection:
        (ended_at,) = connection.execute(
            "SELECT ended_at FROM session WHERE id = ?", (run.sessions[site]["session_id"],)
        ).fetchone()
    assert ended_at is not None


def test_the_test_page_session_records_every_capture_event_type(test_page_run: Run) -> None:
    recorded = {event["type"] for event in events(test_page_run, "test_page")}

    assert sorted(CAPTURE_EVENT_TYPES - recorded) == []
    assert_session_closed(test_page_run, "test_page")
    assert_no_batch_was_dropped(test_page_run)


def test_nothing_typed_on_the_test_page_reaches_the_database(test_page_run: Run) -> None:
    """Se escribió en texto, correo, contraseñas, comentarios y búsqueda."""
    recorded = events(test_page_run, "test_page")

    assert_nothing_typed_is_stored(test_page_run)
    fields = [event for event in recorded if event["type"] in {"focus_in", "field_change"}]
    assert {event["element"]["id"] for event in fields} >= {"name", "email", "password", "comments"}
    assert all(event["element"]["text"] is None for event in fields)


def test_the_test_page_events_follow_the_page(test_page_run: Run) -> None:
    """Los eventos de cada página llevan su dirección, y las validaciones su tipo."""
    recorded = events(test_page_run, "test_page")

    errors = {
        (event["element"]["id"], event["data"]["error_type"])
        for event in recorded
        if event["type"] == "validation_error"
    }
    assert ("password-confirm", "custom_error") in errors
    assert ("terms", "value_missing") in errors
    clicks = [event for event in recorded if event["type"] == "click"]
    answered = {event["data"]["click_t"] for event in recorded if event["type"] == "click_response"}
    dead = [event for event in clicks if event["t"] not in answered]
    assert "dead-button" in {event["element"]["id"] for event in dead}
    assert "counter-button" not in {event["element"]["id"] for event in dead}
    # La captura no deja el puntero ni el scroll en negativo ni fuera de su pantalla.
    assert all(event["x"] >= 0 and event["y"] >= 0 for event in recorded if event["x"] is not None)


@pytest.mark.xfail(
    strict=True,
    reason="capture records no screen_change when a page returns from the back-forward cache",
)
def test_the_test_page_records_each_screen_including_the_return(test_page_run: Run) -> None:
    """Productos y carrito sin recargar, otra página, y de vuelta al carrito con Atrás."""
    recorded = events(test_page_run, "test_page")
    base = recorded[0]["screen"]["url"]
    screens = [
        event["screen"]["url"].removeprefix(base)
        for event in recorded
        if event["type"] == "screen_change"
    ]

    assert screens == [
        "",
        "?view=products#aplicacion",
        "?view=cart#aplicacion",
        "second-page.html",
        "?view=cart#aplicacion",
    ]


@pytest.mark.parametrize("site", ["python_docs", "react"])
def test_a_real_site_session_arrives_complete(external_run: Run, site: str) -> None:
    recorded = events(external_run, site)

    assert sorted(COMMON_EVENT_TYPES - {event["type"] for event in recorded}) == []
    assert_session_closed(external_run, site)
    assert_no_batch_was_dropped(external_run)


def test_real_sites_store_nothing_typed(external_run: Run) -> None:
    """La búsqueda de la documentación viaja en ``?q=``; la de react.dev, en un diálogo."""
    searches = [
        event["screen"]
        for event in events(external_run, "python_docs")
        if event["type"] == "screen_change" and "search.html" in event["screen"]["url"]
    ]

    assert_nothing_typed_is_stored(external_run)
    assert searches, "the search results page was not recorded"
    assert all("q=redacted" in screen["url"] and screen["title"] == "" for screen in searches)


def test_a_single_page_app_records_its_screen_changes(external_run: Run) -> None:
    """react.dev cambia de pantalla sin recargar: ida a otra guía y vuelta con Atrás."""
    urls = [
        event["screen"]["url"]
        for event in events(external_run, "react")
        if event["type"] == "screen_change"
    ]

    assert len(urls) >= 3
    assert urls[0] == urls[-1] == "https://react.dev/learn"
    assert urls[1] != urls[0]
