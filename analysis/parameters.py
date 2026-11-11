"""Parámetros del análisis: umbrales de detección y valores del índice.

Lee ``analysis/parameters.yaml`` y lo convierte en objetos inmutables y
tipados. Un parámetro faltante, desconocido o fuera de rango se detecta al
cargarlo, con un mensaje que nombra la clave. Las etapas reciben el objeto
``Parameters`` y leen sus umbrales como atributos
(``params.rage_click.window_ms``).
"""

import types
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml

DEFAULT_PARAMETERS_PATH = Path(__file__).resolve().parent / "parameters.yaml"
"""Archivo de parámetros por defecto."""

_T = TypeVar("_T")

#: Marca de los campos que admiten 0 además de valores positivos.
_ALLOW_ZERO = {"allow_zero": True}


class ParametersError(ValueError):
    """El archivo de parámetros no existe, no es YAML válido o tiene valores incorrectos."""


@dataclass(frozen=True)
class RageClickParams:
    """Ráfaga de clics rápidos en un área pequeña.

    Attributes:
        min_clicks: Clics mínimos de la ráfaga.
        window_ms: Ventana de tiempo en que deben ocurrir.
        radius_px: Distancia máxima entre clics, en píxeles CSS.
    """

    min_clicks: int
    window_ms: int
    radius_px: int


@dataclass(frozen=True)
class DeadClickParams:
    """Clic sin respuesta de la página.

    Attributes:
        wait_ms: Espera sin cambios en la página después del clic.
    """

    wait_ms: int


@dataclass(frozen=True)
class RepeatedSearchParams:
    """Búsqueda repetida.

    Attributes:
        min_searches: Búsquedas mínimas para considerarla repetida.
        window_ms: Ventana de tiempo en que deben ocurrir.
    """

    min_searches: int
    window_ms: int


@dataclass(frozen=True)
class GazeParams:
    """Medición y reprocesamiento de la mirada después de la sesión.

    Attributes:
        pursuit_skip_ms: Tramo inicial del punto en movimiento de la calibración
            que se descarta: los ojos tardan en engancharse a un objetivo que
            empieza a moverse.
        saccade_deg_per_s: Velocidad de la mirada desde la que se considera un
            salto (sacada): el suavizado no la cruza.
        fixation_dispersion_deg: Dispersión máxima de una fijación (algoritmo I-DT).
        fixation_min_ms: Duración mínima de una fijación.
        smoothing_deg_per_s: Cuánto puede moverse la mirada por segundo dentro
            de una fijación, en el suavizado de Kalman (ruido del proceso).
    """

    pursuit_skip_ms: float
    saccade_deg_per_s: float
    fixation_dispersion_deg: float
    fixation_min_ms: float
    smoothing_deg_per_s: float


@dataclass(frozen=True)
class Parameters:
    """Todos los parámetros del análisis.

    Attributes:
        version: Versión del conjunto de parámetros; se guarda con cada índice.
        rage_click: Umbrales de las ráfagas de clics.
        dead_click: Umbrales de los clics sin respuesta.
        long_pause_ms: Inactividad mínima de una pausa prolongada.
        hesitation_ms: Tiempo con el cursor detenido sobre un elemento
            interactivo sin activarlo.
        navigation_loop_window: Últimas pantallas en las que se busca el patrón
            A → B → A.
        repeated_search: Umbrales de las búsquedas repetidas.
        task_overtime_factor: Veces el tiempo de la referencia a partir de las
            cuales una tarea está excedida.
        friction_i_max: Incidentes por minuto de tarea con los que la fricción
            llega a 0, o ``None`` mientras no se fije con el piloto.
        camera_delay_ms: Retraso de la cámara respecto de los eventos (0 o más).
        gaze: Medición y reprocesamiento de la mirada.
    """

    version: str
    rage_click: RageClickParams
    dead_click: DeadClickParams
    long_pause_ms: int
    hesitation_ms: int
    navigation_loop_window: int
    repeated_search: RepeatedSearchParams
    task_overtime_factor: float
    friction_i_max: float | None
    camera_delay_ms: float = field(metadata=_ALLOW_ZERO)
    gaze: GazeParams


def load_parameters(path: Path | str | None = None) -> Parameters:
    """Carga y valida los parámetros.

    Args:
        path: Archivo YAML a leer; por defecto, ``analysis/parameters.yaml``.

    Returns:
        Parámetros inmutables.

    Raises:
        ParametersError: Si el archivo no existe, no es YAML válido o algún
            valor no cumple las reglas. El mensaje nombra el archivo y la clave.
    """
    parameters_path = Path(path or DEFAULT_PARAMETERS_PATH)
    try:
        data = yaml.safe_load(parameters_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ParametersError(f"parameters file not found: {parameters_path}") from None
    except yaml.YAMLError as error:
        raise ParametersError(f"{parameters_path}: invalid YAML: {error}") from None
    try:
        return _build(Parameters, data, "")
    except ParametersError as error:
        raise ParametersError(f"{parameters_path}: {error}") from None


def _build(cls: type[_T], data: Any, key: str) -> _T:
    """Construye una dataclass de parámetros a partir de un objeto YAML.

    Exige exactamente las claves de la dataclass: una clave faltante o
    desconocida es un error, para detectar erratas.

    Args:
        cls: Dataclass que se construye.
        data: Objeto YAML con sus valores.
        key: Ruta de la sección, para los mensajes (vacía en la raíz).

    Returns:
        Instancia validada.

    Raises:
        ParametersError: Si faltan o sobran claves, o algún valor no es válido.
    """
    label = key or "parameters"
    if not isinstance(data, dict):
        raise ParametersError(f"{label}: expected a mapping")
    expected = {item.name: item for item in fields(cls)}
    missing = sorted(expected.keys() - data.keys())
    unknown = sorted(data.keys() - expected.keys())
    if missing:
        raise ParametersError(f"{label}: missing keys {missing}")
    if unknown:
        raise ParametersError(f"{label}: unknown keys {unknown}")
    values = {
        name: _convert(f"{key}.{name}" if key else name, data[name], item.type, item.metadata)
        for name, item in expected.items()
    }
    return cls(**values)


def _convert(key: str, value: Any, field_type: Any, metadata: Any) -> Any:
    """Comprueba el tipo y el rango de un valor.

    Los números deben ser positivos, salvo los campos marcados para admitir 0.

    Args:
        key: Ruta de la clave, para los mensajes.
        value: Valor leído del YAML.
        field_type: Tipo declarado en la dataclass.
        metadata: Metadatos del campo.

    Returns:
        Valor validado; los números de campos ``float`` se convierten a ``float``.

    Raises:
        ParametersError: Si el valor no es del tipo esperado o está fuera de rango.
    """
    if is_dataclass(field_type):
        return _build(field_type, value, key)
    if isinstance(field_type, types.UnionType):
        # float | None: null es válido; si no, el valor sigue las reglas de float.
        if value is None:
            return None
        field_type = float
    if field_type is str:
        if not isinstance(value, str) or not value.strip():
            raise ParametersError(f"{key}: expected a non-empty string, got {value!r}")
        return value
    # bool es subclase de int en Python; true no es un número válido aquí.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParametersError(f"{key}: expected a number, got {value!r}")
    if field_type is int and not isinstance(value, int):
        raise ParametersError(f"{key}: expected an integer, got {value!r}")
    minimum_ok = value >= 0 if metadata.get("allow_zero") else value > 0
    if not minimum_ok:
        rule = "must be zero or positive" if metadata.get("allow_zero") else "must be positive"
        raise ParametersError(f"{key}: {rule}, got {value}")
    return float(value) if field_type is float else value
