"""Fábrica de la aplicación FastAPI del servidor local.

``create_app`` es el punto de composición del servidor: comprueba la base,
define cómo se abre el repositorio de cada petición, registra los endpoints con
la comprobación del token y traduce las excepciones de ``services`` a respuestas
HTTP. Las pruebas crean la app con otra configuración.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server import routes
from server.repositories import SqliteRepository
from server.security import token_checker
from server.services import ConflictError, ErrorItem, InvalidRequestError, NotFoundError
from shared import contracts, db
from shared.config import Config


def create_app(config: Config) -> FastAPI:
    """Crea la aplicación del servidor.

    Args:
        config: Configuración completa; se usan ``server`` y ``database``.

    Returns:
        Aplicación lista para servir.

    Raises:
        FileNotFoundError: Si la base de datos no existe.
        SchemaVersionError: Si la base tiene otra versión del esquema.
    """
    # Se comprueba al arrancar, no en la primera petición, para fallar rápido.
    db.open_database(config.database.path).close()

    app = FastAPI(
        title="SUCA local server",
        version=contracts.contract_version(),
        description="Recibe, valida y guarda los datos de las sesiones.",
    )
    app.state.config = config
    app.state.open_repository = _repository_factory(config)
    app.include_router(routes.router, dependencies=[Depends(token_checker(config.server.token))])
    _add_error_handlers(app)
    return app


def _repository_factory(config: Config) -> Callable[[], AbstractContextManager[SqliteRepository]]:
    """Crea la función que abre el repositorio de una petición.

    Cada petición usa su propia conexión, que se cierra al terminar. Las
    capturas de pantalla se guardan junto a la base, en ``captures/``. FastAPI
    abre, usa y cierra esa conexión en hilos distintos; por eso se abre con
    ``check_same_thread=False``, que es seguro porque la conexión nunca se usa
    desde dos hilos a la vez.

    Args:
        config: Configuración con la ruta de la base.

    Returns:
        Función sin argumentos que devuelve un administrador de contexto con un
        ``SqliteRepository``.
    """

    @contextmanager
    def open_repository() -> Iterator[SqliteRepository]:
        connection = db.open_database(config.database.path, check_same_thread=False)
        try:
            yield SqliteRepository(connection, data_dir=config.database.path.parent)
        finally:
            connection.close()

    return open_repository


def _add_error_handlers(app: FastAPI) -> None:
    """Traduce las excepciones de los servicios a respuestas HTTP.

    Todos los errores tienen la forma ``{"detail": ...}``; los 422 agregan
    ``errors``, una lista de ``{record, field, message}``.

    Args:
        app: Aplicación a la que se agregan los manejadores.
    """

    @app.exception_handler(NotFoundError)
    def not_found(request: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(ConflictError)
    def conflict(request: Request, error: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(InvalidRequestError)
    def invalid(request: Request, error: InvalidRequestError) -> JSONResponse:
        return _unprocessable(str(error), error.errors)

    @app.exception_handler(RequestValidationError)
    def malformed(request: Request, error: RequestValidationError) -> JSONResponse:
        # El primer elemento de "loc" es la parte de la petición (body, path…). En
        # un JSON mal formado, el resto es la posición en el texto, no un campo.
        items = [
            ErrorItem(
                record=None,
                field=""
                if detail["type"] == "json_invalid"
                else "/".join(str(part) for part in detail["loc"][1:]),
                message=detail["msg"],
            )
            for detail in error.errors()
        ]
        return _unprocessable("malformed request", items)


def _unprocessable(message: str, errors: tuple[ErrorItem, ...] | list[ErrorItem]) -> JSONResponse:
    """Arma una respuesta 422 con la lista de errores.

    Args:
        message: Resumen del problema.
        errors: Problemas encontrados.

    Returns:
        Respuesta HTTP 422.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": message, "errors": [asdict(item) for item in errors]},
    )
