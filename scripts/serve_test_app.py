"""Sirve la app de prueba (``test-app/public/``) por HTTP.

La app es de una sola página con rutas reales (``/product/101``, ``/cart``…),
así que cualquier ruta sin extensión que no sea un archivo devuelve
``index.html``: recargar la página o abrir un enlace directo funciona igual que
en un sitio publicado. Los archivos que no existen (``/js/nada.js``) siguen
respondiendo 404.

El puerto sale de la configuración (``test_app.port``) y solo se escucha en
``127.0.0.1``.

Uso::

    python -m scripts.serve_test_app
"""

import argparse
import posixpath
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from shared.config import ROOT_DIR, load_config

#: Carpeta pública de la app de prueba.
TEST_APP_DIR = ROOT_DIR / "test-app" / "public"

#: Solo se escucha en la propia computadora.
HOST = "127.0.0.1"

#: Documento que atiende las rutas de la aplicación.
INDEX = "/index.html"


class TestAppHandler(SimpleHTTPRequestHandler):
    """Archivos estáticos con respaldo a ``index.html`` para las rutas de la app.

    Attributes:
        extensions_map: Tipos MIME fijos para los archivos de la app.
    """

    # Evita que pytest intente recolectar esta clase por empezar con "Test".
    __test__ = False

    # En Windows, ``mimetypes`` lee el registro del sistema y puede asociar
    # ``.js`` a ``text/plain``; Chrome rechaza así los módulos de JavaScript.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
        ".json": "application/json",
    }

    def send_head(self) -> BinaryIO | None:
        """Reescribe las rutas de la app a ``index.html`` antes de servir.

        Returns:
            Lo mismo que ``SimpleHTTPRequestHandler.send_head``: el archivo
            abierto, o ``None`` si ya se respondió con un error.
        """
        path = unquote(urlsplit(self.path).path)
        if _is_app_route(path) and not Path(self.translate_path(path)).exists():
            self.path = INDEX
        return super().send_head()

    def list_directory(self, path: str) -> None:
        """No muestra el contenido de las carpetas: un sitio real no lo hace.

        Args:
            path: Carpeta pedida.
        """
        self.send_error(404, "Not found")

    def end_headers(self) -> None:
        """Pide no guardar en caché, para que un cambio se vea al recargar."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def _is_app_route(path: str) -> bool:
    """Indica si una ruta parece de la aplicación y no de un archivo.

    Args:
        path: Ruta de la URL, sin la consulta.

    Returns:
        ``True`` si el último segmento no tiene extensión (``/cart``,
        ``/order/5012/confirmation``).
    """
    return "." not in posixpath.basename(path.rstrip("/"))


def create_server(port: int, directory: Path = TEST_APP_DIR) -> ThreadingHTTPServer:
    """Crea el servidor de la app de prueba, sin iniciarlo.

    Args:
        port: Puerto en el que escucha; 0 elige uno libre.
        directory: Carpeta pública que se sirve.

    Returns:
        Servidor listo para ``serve_forever``.
    """
    handler = partial(TestAppHandler, directory=str(directory))
    return ThreadingHTTPServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 al detenerlo con Ctrl+C.
    """
    argparse.ArgumentParser(description="Sirve la app de prueba.").parse_args(argv)
    port = load_config().test_app.port
    with create_server(port) as server:
        print(f"test app at http://{HOST}:{port}/ (Ctrl+C to stop)")
        print(f"evaluator setup at http://{HOST}:{port}/setup")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
