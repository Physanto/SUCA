"""Pruebas del servidor de la página de prueba (``scripts.serve_test_page``)."""

import threading
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from scripts.serve_test_page import HOST, TEST_PAGE_DIR, create_server


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    """Sirve la página de prueba en un puerto libre mientras dura la prueba."""
    with create_server(0) as running:
        thread = threading.Thread(target=running.serve_forever, daemon=True)
        thread.start()
        yield running
        running.shutdown()


def fetch(server: ThreadingHTTPServer, path: str) -> tuple[int, str]:
    """Pide una ruta al servidor y devuelve el código y el contenido."""
    url = f"http://{HOST}:{server.server_address[1]}{path}"
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def test_test_page_files_exist() -> None:
    for name in ("index.html", "second-page.html", "app.js", "styles.css"):
        assert (TEST_PAGE_DIR / name).is_file(), name


def test_serves_the_test_page_on_loopback(server: ThreadingHTTPServer) -> None:
    status, body = fetch(server, "/")

    assert server.server_address[0] == "127.0.0.1"
    assert status == 200
    assert "Página de prueba" in body


def test_serves_the_page_scripts(server: ThreadingHTTPServer) -> None:
    status, body = fetch(server, "/app.js")

    assert status == 200
    assert "history.pushState" in body
