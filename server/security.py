"""Comprobación del token de desarrollo local en cada petición.

El servidor escucha solo en ``127.0.0.1``; el token no protege frente a otras
computadoras, sino que evita que una página web abierta en el navegador escriba
en el servidor por accidente. Las páginas web no pueden enviar el encabezado
``X-Api-Token`` sin una consulta previa de CORS que el servidor no autoriza.
"""

import hmac
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

TOKEN_HEADER = "X-Api-Token"
"""Encabezado que lleva el token."""

_token_header = APIKeyHeader(
    name=TOKEN_HEADER,
    auto_error=False,
    description="Token de desarrollo local definido en config/shared.json.",
)


def token_checker(expected_token: str) -> Callable[..., None]:
    """Crea la dependencia de FastAPI que exige el token en una petición.

    Args:
        expected_token: Token de la configuración (``server.token``).

    Returns:
        Dependencia que no devuelve nada si el token es correcto.
    """
    expected = expected_token.encode()

    def require_token(token: Annotated[str | None, Depends(_token_header)]) -> None:
        """Rechaza la petición si el token falta o no coincide.

        Args:
            token: Valor del encabezado ``X-Api-Token``, si vino.

        Raises:
            HTTPException: 401 si el token falta o no coincide.
        """
        # compare_digest tarda lo mismo acierte o no, para no filtrar el token por tiempos.
        if token is None or not hmac.compare_digest(token.encode(), expected):
            raise HTTPException(status_code=401, detail=f"missing or invalid {TOKEN_HEADER} header")

    return require_token
