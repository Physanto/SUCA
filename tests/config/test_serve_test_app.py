"""Pruebas del servidor de la app de prueba (``scripts.serve_test_app``)."""

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from scripts.serve_test_app import HOST, TEST_APP_DIR, create_server


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    """Sirve la app de prueba en un puerto libre mientras dura la prueba."""
    with create_server(0) as running:
        thread = threading.Thread(target=running.serve_forever, daemon=True)
        thread.start()
        yield running
        running.shutdown()


def fetch(server: ThreadingHTTPServer, path: str) -> tuple[int, str, str]:
    """Pide una ruta y devuelve el código, el tipo de contenido y el cuerpo."""
    url = f"http://{HOST}:{server.server_address[1]}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, response.headers["Content-Type"], body
    except urllib.error.HTTPError as error:
        return error.code, error.headers["Content-Type"], ""


def test_entry_files_exist() -> None:
    for name in ("index.html", "js/main.js", "css/styles.css"):
        assert (TEST_APP_DIR / name).is_file(), name


def test_serves_the_app_on_loopback(server: ThreadingHTTPServer) -> None:
    status, content_type, body = fetch(server, "/")

    assert server.server_address[0] == "127.0.0.1"
    assert status == 200
    assert content_type.startswith("text/html")
    assert '<script type="module"' in body


@pytest.mark.parametrize(
    "path",
    ["/login", "/product/101", "/order/5012/confirmation", "/search?q=audifonos", "/cart/"],
)
def test_app_routes_return_the_index(server: ThreadingHTTPServer, path: str) -> None:
    status, content_type, body = fetch(server, path)

    assert status == 200
    assert content_type.startswith("text/html")
    assert '<script type="module"' in body


def test_scripts_are_served_as_javascript(server: ThreadingHTTPServer) -> None:
    status, content_type, _ = fetch(server, "/js/main.js")

    assert status == 200
    assert content_type.startswith("text/javascript")


def test_missing_files_are_not_found(server: ThreadingHTTPServer) -> None:
    status, _, _ = fetch(server, "/js/missing.js")

    assert status == 404


def test_folders_are_not_listed(server: ThreadingHTTPServer) -> None:
    status, _, _ = fetch(server, "/js/")

    assert status == 404
