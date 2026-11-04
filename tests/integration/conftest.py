"""Fixtures de las pruebas de integración en Chrome (I1, I2…).

``live_database`` levanta el servidor local real con una base nueva, en la
dirección de la configuración, porque la extensión la tiene fija. Dura lo que
dura el módulo de pruebas que la pide: dos módulos no comparten servidor ni
base, y el puerto queda libre para el siguiente.
"""

import dataclasses
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from scripts.simulation import store
from server.app import create_app
from shared.config import load_config

#: Tiempo máximo para que el servidor local arranque, en segundos.
SERVER_START_TIMEOUT_S = 10


def _port_is_free(host: str, port: int) -> bool:
    """Indica si nadie escucha en el puerto."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        return probe.connect_ex((host, port)) != 0


@pytest.fixture(scope="module")
def live_database(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    """Servidor real con una base nueva (con el estudio de ejemplo cargado).

    Falla si ya hay algo escuchando en la dirección de la configuración: un
    servidor local en marcha recibiría los lotes de la prueba en su propia base.

    Yields:
        Ruta de la base que llena el servidor.
    """
    import uvicorn

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    config = load_config()
    host, port = config.server.host, config.server.port
    if not _port_is_free(host, port):
        pytest.fail(f"something is already listening on {host}:{port}; stop the local server")
    folder = request.module.__name__.rsplit(".", 1)[-1]
    path = tmp_path_factory.mktemp(folder) / "suca.db"
    store.create_database(path).close()
    config = dataclasses.replace(config, database=dataclasses.replace(config.database, path=path))
    server = uvicorn.Server(
        uvicorn.Config(create_app(config), host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + SERVER_START_TIMEOUT_S
    while not server.started:
        if time.monotonic() > deadline:
            pytest.fail("the local server did not start")
        time.sleep(0.05)
    yield path
    server.should_exit = True
    thread.join(timeout=10)
