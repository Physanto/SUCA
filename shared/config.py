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
        video_width: Ancho de video que se pide a la webcam, en píxeles.
        video_height: Alto de video que se pide a la webcam, en píxeles.
        viewing_distance_cm: Distancia del participante a la pantalla, para
            pasar el error de calibración de píxeles a grados.
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla del
            laboratorio (37.8 corresponde a 96 píxeles por pulgada).
        distance_scale: Corrección de la distancia a la cámara que estima
            MediaPipe, propia de cada webcam: distancia medida con un metro
            dividida por la distancia que muestra la calibración (1.0 sin ajustar).
        min_distance_cm: Distancia mínima aceptable a la cámara antes de calibrar.
        max_distance_cm: Distancia máxima aceptable a la cámara antes de calibrar.
        calibration_max_error_deg: Error medio máximo, en grados, para aceptar
            una calibración. Provisional hasta el piloto.
        lock_exposure: Si se fijan la exposición, el foco y el balance de
            blancos de la webcam unos segundos después de abrirla, para que la
            imagen de los ojos no cambie con la luz de la pantalla. Solo en las
            webcams que lo permiten.
        blink_threshold: Valor de parpadeo de MediaPipe (entre 0 y 1) a partir
            del cual el cuadro se considera un parpadeo.
        off_screen_margin_px: Distancia fuera de la ventana, en píxeles CSS, a
            partir de la cual la mirada se considera fuera de la pantalla y no
            un error de estimación cerca del borde.
        head_range_margin_deg: Grados que la cabeza puede salir del rango de
            giro visto en la calibración antes de considerar que mira fuera de
            la pantalla. Dentro del margen, la muestra tiene confianza baja.
        gaze_hybrid: Si el motor combina los estimadores geométrico y de
            apariencia según la postura cuando ambos entrenaron. En ``false``
            usa solo el de menor error de validación cruzada, para comparar
            ambos modos en el banco de pruebas.
        filter_min_cutoff_hz: Frecuencia de corte mínima del filtro One Euro:
            más baja suaviza más las fijaciones.
        filter_beta: Cuánto sube el corte con la velocidad de la mirada en el
            filtro One Euro: más alta sigue antes los saltos de mirada.
        drift_check_between_tasks: Si el panel pide una comprobación de deriva
            al terminar cada tarea del modo guiado (salvo la última).
        drift_correction: Si una comprobación de deriva corrige la mirada. Sin
            corrección solo mide, como en las sesiones del banco de pruebas.
        drift_correction_min_error_deg: Error mínimo, en grados, para que una
            comprobación de deriva corrija.
        record_gaze_features: Si se registran las características de mirada de
            cada cuadro (lote ``gaze_features``), que permiten medir y
            reprocesar la mirada después de la sesión.
    """

    gaze_hz: int
    face_hz: int
    video_width: int
    video_height: int
    viewing_distance_cm: float
    css_px_per_cm: float
    distance_scale: float
    min_distance_cm: float
    max_distance_cm: float
    calibration_max_error_deg: float
    lock_exposure: bool
    blink_threshold: float
    off_screen_margin_px: float
    head_range_margin_deg: float
    gaze_hybrid: bool
    filter_min_cutoff_hz: float
    filter_beta: float
    drift_check_between_tasks: bool
    drift_correction: bool
    drift_correction_min_error_deg: float
    record_gaze_features: bool

    def __post_init__(self) -> None:
        """Valida el rango de distancias y que el umbral de parpadeo sea una fracción."""
        if self.min_distance_cm >= self.max_distance_cm:
            raise ConfigError(
                "camera.min_distance_cm must be less than camera.max_distance_cm, got "
                f"{self.min_distance_cm} and {self.max_distance_cm}"
            )
        if self.blink_threshold >= 1:
            raise ConfigError(
                f"camera.blink_threshold must be less than 1, got {self.blink_threshold}"
            )


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
class TestAppConfig:
    """Servidor estático de la app de prueba (``test-app/``).

    Attributes:
        port: Puerto en el que se sirve la app.
    """

    # Evita que pytest intente recolectar esta clase por empezar con "Test".
    __test__ = False

    port: int

    def __post_init__(self) -> None:
        """Valida el puerto."""
        _check_port("test_app.port", self.port)


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
        test_app: App de prueba.
    """

    server: ServerConfig
    database: DatabaseConfig
    sending: SendingConfig
    capture: CaptureConfig
    camera: CameraConfig
    test_page: TestPageConfig
    test_app: TestAppConfig


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
    if field_type is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{key}: expected true or false, got {value!r}")
        return value
    if field_type is int:
        # bool es subclase de int en Python; true no es un número válido aquí.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{key}: expected an integer, got {value!r}")
        if value <= 0:
            raise ConfigError(f"{key}: must be positive, got {value}")
        return value
    if field_type is float:
        # Se aceptan enteros (60) y decimales (37.8); bool no es un número aquí.
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ConfigError(f"{key}: expected a number, got {value!r}")
        if not value > 0:
            raise ConfigError(f"{key}: must be positive, got {value}")
        return float(value)
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
