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

#: Marca de los campos que son una probabilidad: mayores que 0 y menores que 1.
_PROBABILITY = {"probability": True}


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
class AttentionParams:
    """Atribución de cada fijación a los elementos de la pantalla, con probabilidades.

    Attributes:
        unassigned_prior: Probabilidad previa de que una fijación no esté sobre
            ningún elemento (mira el vacío, está distraída o pensando).
        natural_error_factor: Veces que el error de la mirada en uso natural
            supera al medido en los puntos de control, donde la persona fija un
            punto a propósito.
        default_error_deg: Error medio de la mirada si la sesión no lo midió.
        low_confidence_factor: Veces que crece el error en una fijación con
            confianza baja (postura fuera de la calibrada, vuelta de mirar fuera).
        candidate_radius_sigma: Distancia máxima, en desvíos del error, entre la
            fijación y un elemento candidato.
        stay_weight: Veces que es más probable volver a fijar el mismo elemento
            que pasar a otro cualquiera.
        near_weight: Peso extra de pasar a un elemento cercano.
        near_distance_deg: Distancia en que el peso extra de un elemento cercano
            cae a un tercio (e⁻¹).
        sequence_max_gap_ms: Hueco entre fijaciones desde el que la anterior ya
            no informa sobre la siguiente.
        interaction_window_ms: Tramo antes de un clic o un foco en que una
            fijación se considera preparación de esa interacción.
        interaction_likelihood_ratio: Veces que una interacción con un elemento
            hace más verosímil que la fijación previa estuviera sobre él. Solo en
            la atención estimada, nunca en la atribución por la mirada sola.
        confident_probability: Probabilidad desde la que un elemento (o el
            ancestro que reúne a los candidatos) se da por mirado.
        long_stare_ms: Duración desde la que una fijación sin interacción ni
            scroll se marca como mirada fija prolongada.
        min_probability: Probabilidad mínima de un candidato para guardarlo.
    """

    unassigned_prior: float = field(metadata=_PROBABILITY)
    natural_error_factor: float
    default_error_deg: float
    low_confidence_factor: float
    candidate_radius_sigma: float
    stay_weight: float
    near_weight: float
    near_distance_deg: float
    sequence_max_gap_ms: float
    interaction_window_ms: float
    interaction_likelihood_ratio: float
    confident_probability: float = field(metadata=_PROBABILITY)
    long_stare_ms: float
    min_probability: float = field(metadata=_PROBABILITY)


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
        attention: Atribución de la mirada a los elementos de la pantalla.
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
    attention: AttentionParams


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

    Los números deben ser positivos, salvo los campos marcados para admitir 0;
    las probabilidades, además, menores que 1.

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
    if metadata.get("probability") and value >= 1:
        raise ParametersError(f"{key}: must be a probability below 1, got {value}")
    return float(value) if field_type is float else value
