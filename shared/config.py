"""Carga y validación de la configuración única del sistema.

Lee ``config/shared.json``, o el archivo que indique la variable de entorno
``SUCA_CONFIG``, y lo convierte en objetos inmutables y tipados. Un error en la
configuración se detecta al cargarla, con un mensaje que nombra la clave.

Cada consumidor recibe solo la sección que necesita: el servidor
``config.server``, quien abre la base de datos ``config.database``, etc.
"""

import ipaddress
import json
import os
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

ROOT_DIR = Path(__file__).resolve().parent.parent
"""Raíz del repositorio. Las rutas relativas de la configuración parten de aquí."""

DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "shared.json"
"""Archivo de configuración por defecto."""

CONFIG_ENV_VAR = "SUCA_CONFIG"
"""Variable de entorno con la ruta de otro archivo de configuración (para pruebas)."""

_T = TypeVar("_T")


class ConfigError(ValueError):
    """La configuración no existe, no es JSON válido o tiene valores incorrectos."""


@dataclass(frozen=True)
class ServerConfig:
    """Servidor local.

    Attributes:
        host: Dirección en la que escucha; debe ser de loopback (127.0.0.1).
        port: Puerto del servidor.
        token: Token de desarrollo local que se envía en ``X-Api-Token``.
    """

    host: str
    port: int
    token: str

    def __post_init__(self) -> None:
        """Valida que el servidor solo sea accesible desde la misma computadora."""
        try:
            is_loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ConfigError(f"server.host: must be a loopback IP address, got {self.host!r}")
        _check_port("server.port", self.port)


@dataclass(frozen=True)
class DatabaseConfig:
    """Bases de datos SQLite.

    Attributes:
        path: Base de datos de las sesiones reales.
        mock_path: Base de datos de los datos simulados.
    """

    path: Path
    mock_path: Path


@dataclass(frozen=True)
class SendingConfig:
    """Envío de lotes desde la extensión al servidor.

    Attributes:
        interval_ms: Cada cuánto se entrega lo acumulado.
        max_batch_records: Registros a partir de los cuales se entrega antes de tiempo.
        retry_initial_ms: Espera antes del primer reintento.
        retry_max_ms: Espera máxima entre reintentos.
    """

    interval_ms: int
    max_batch_records: int
    retry_initial_ms: int
    retry_max_ms: int

    def __post_init__(self) -> None:
        """Valida que la espera de reintento pueda crecer hasta el máximo."""
        if self.retry_initial_ms > self.retry_max_ms:
            raise ConfigError("sending.retry_initial_ms: must not exceed sending.retry_max_ms")


@dataclass(frozen=True)
class CaptureConfig:
    """Captura de interacción.

    Attributes:
        mousemove_hz: Frecuencia máxima de muestreo del cursor.
        scroll_hz: Frecuencia máxima de registro del scroll.
        click_response_wait_ms: Espera tras un clic para ver si la página respondió.
    """

    mousemove_hz: int
    scroll_hz: int
    click_response_wait_ms: int


@dataclass(frozen=True)
class CameraConfig:
    """Módulo de cámara.

    Attributes:
        gaze_hz: Frecuencia de muestreo de la mirada.
        face_hz: Frecuencia de muestreo de los movimientos faciales.
    """

    gaze_hz: int
    face_hz: int


@dataclass(frozen=True)
class TestPageConfig:
    """Servidor estático de la página de prueba de la extensión.

    Attributes:
        port: Puerto en el que se sirve la página.
    """

    # Evita que pytest intente recolectar esta clase por empezar con "Test".
    __test__ = False

    port: int

    def __post_init__(self) -> None:
        """Valida el puerto."""
        _check_port("test_page.port", self.port)


@dataclass(frozen=True)
class Config:
    """Configuración completa del sistema.

    Attributes:
        server: Servidor local.
        database: Bases de datos.
        sending: Envío de lotes.
        capture: Captura de interacción.
        camera: Módulo de cámara.
        test_page: Página de prueba.
    """

    server: ServerConfig
    database: DatabaseConfig
    sending: SendingConfig
    capture: CaptureConfig
    camera: CameraConfig
    test_page: TestPageConfig


def load_config(path: Path | str | None = None) -> Config:
    """Carga y valida la configuración.

    Args:
        path: Archivo a leer. Si se omite, se usa la variable de entorno
            ``SUCA_CONFIG`` y, si tampoco existe, ``config/shared.json``.

    Returns:
        Configuración inmutable.

    Raises:
        ConfigError: Si el archivo no existe, no es JSON válido o algún valor
            no cumple las reglas. El mensaje nombra el archivo y la clave.
    """
    config_path = Path(path or os.environ.get(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {config_path}") from None
    except json.JSONDecodeError as error:
        raise ConfigError(f"{config_path}: invalid JSON: {error}") from None
    try:
        return _build(Config, data, "")
    except ConfigError as error:
        raise ConfigError(f"{config_path}: {error}") from None


def _build(cls: type[_T], data: Any, key: str) -> _T:
    """Construye una dataclass de configuración a partir de un objeto JSON.

    Exige exactamente las claves de la dataclass: una clave faltante o
    desconocida es un error, para detectar erratas.

    Args:
        cls: Dataclass que se construye.
        data: Objeto JSON con sus valores.
        key: Ruta de la sección, para los mensajes de error (vacía en la raíz).

    Returns:
        Instancia validada.

    Raises:
        ConfigError: Si faltan o sobran claves, o algún valor no es válido.
    """
    label = key or "configuration"
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: expected an object")
    expected = {field.name: field.type for field in fields(cls)}
    missing = sorted(expected.keys() - data.keys())
    unknown = sorted(data.keys() - expected.keys())
    if missing:
        raise ConfigError(f"{label}: missing keys {missing}")
    if unknown:
        raise ConfigError(f"{label}: unknown keys {unknown}")
    values = {
        name: _convert(f"{key}.{name}" if key else name, data[name], field_type)
        for name, field_type in expected.items()
    }
    return cls(**values)


def _convert(key: str, value: Any, field_type: Any) -> Any:
    """Comprueba el tipo de un valor y lo convierte al de su campo.

    Args:
        key: Ruta de la clave, para los mensajes de error.
        value: Valor leído del JSON.
        field_type: Tipo declarado en la dataclass.

    Returns:
        Valor convertido. Las rutas relativas se resuelven desde la raíz del
        repositorio.

    Raises:
        ConfigError: Si el valor no es del tipo esperado o no es válido.
    """
    if is_dataclass(field_type):
        return _build(field_type, value, key)
    if field_type is int:
        # bool es subclase de int en Python; true no es un número válido aquí.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{key}: expected an integer, got {value!r}")
        if value <= 0:
            raise ConfigError(f"{key}: must be positive, got {value}")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key}: expected a non-empty string, got {value!r}")
    if field_type is Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT_DIR / path
    return value


def _check_port(key: str, port: int) -> None:
    """Valida que un número sea un puerto TCP.

    Args:
        key: Ruta de la clave, para el mensaje de error.
        port: Puerto a validar.

    Raises:
        ConfigError: Si el puerto está fuera del rango 1-65535.
    """
    if not 1 <= port <= 65535:
        raise ConfigError(f"{key}: must be between 1 and 65535, got {port}")
