"""Sirve la página de prueba de la extensión por HTTP.

Los content scripts de la extensión no corren en las páginas de la propia
extensión, así que la página de prueba (``extension/test-page/``) se abre como
un sitio web normal, en ``http://127.0.0.1:<test_page.port>/``. El puerto sale
de la configuración (``test_page.port``).

Uso::

    python -m scripts.serve_test_page
"""

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from shared.config import ROOT_DIR, load_config

#: Carpeta de la página de prueba.
TEST_PAGE_DIR = ROOT_DIR / "extension" / "test-page"

#: Solo se escucha en la propia computadora.
HOST = "127.0.0.1"


def create_server(port: int, directory: Path = TEST_PAGE_DIR) -> ThreadingHTTPServer:
    """Crea el servidor estático de la página de prueba, sin iniciarlo.

    Args:
        port: Puerto en el que escucha; 0 elige uno libre.
        directory: Carpeta que se sirve.

    Returns:
        Servidor listo para ``serve_forever``.
    """
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    return ThreadingHTTPServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 al detenerlo con Ctrl+C.
    """
    argparse.ArgumentParser(description="Sirve la página de prueba de la extensión.").parse_args(
        argv
    )
    port = load_config().test_page.port
    with create_server(port) as server:
        print(f"test page at http://{HOST}:{port}/ (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
