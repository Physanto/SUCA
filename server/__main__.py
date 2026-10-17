"""Arranca el servidor local: ``python -m server``.

Escucha en ``server.host`` y ``server.port`` de ``config/shared.json``. La
configuración solo admite una dirección de loopback, así que el servidor nunca
queda accesible desde otras computadoras.
"""

import sys

import uvicorn

from server.app import create_app
from shared import db
from shared.config import ConfigError, load_config


def main() -> int:
    """Carga la configuración, crea la app y la sirve hasta que se detenga.

    Returns:
        Código de salida: 0 al detenerse normalmente, 1 si no pudo arrancar.
    """
    try:
        config = load_config()
        app = create_app(config)
    except (ConfigError, FileNotFoundError, db.SchemaVersionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    uvicorn.run(app, host=config.server.host, port=config.server.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
