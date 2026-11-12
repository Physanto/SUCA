"""Columnas y tipos de los DataFrames que pasan entre las etapas del análisis.

Hay dos grupos de tablas:

- **Resultados** (``episode``, ``incident``, ``task_result``,
  ``usability_index``): lo que producen las etapas y se guarda en la base. Sus
  columnas deben ser exactamente las de aquí, sin ``session_id`` (lo agrega el
  repositorio al guardar) ni ``params_version`` (también).
- **Datos de la sesión** (``events``, ``gaze``, ``face``, ``calibrations``,
  ``tasks``, ``references``): lo que entrega el repositorio en ``SessionData``.
  Las columnas de aquí son obligatorias; una etapa puede agregar otras.

Cada columna tiene un tipo lógico:

- ``float``: número (``float64``);
- ``int``: entero, también con vacíos (``Int64``);
- ``bool``: verdadero o falso;
- ``text``: texto;
- ``json``: diccionario o lista, que se guarda como JSON.

``frame`` y ``empty`` crean DataFrames con esos tipos. ``validate`` comprueba un
DataFrame y explica todo lo que está mal en un solo error.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd
from pandas.api import types as ptypes

from shared import contracts


class ColumnValidationError(ValueError):
    """Un DataFrame no tiene las columnas, los tipos o los valores esperados.

    Attributes:
        table: Tabla contra la que se validó.
        problems: Cada problema encontrado, en inglés.
    """

    def __init__(self, label: str, table: str, problems: Iterable[str]) -> None:
        """Arma el mensaje con todos los problemas.

        Args:
            label: Qué produjo el DataFrame (una etapa, un detector) o la tabla.
            table: Tabla contra la que se validó.
            problems: Problemas encontrados.
        """
        self.table = table
        self.problems = tuple(problems)
        super().__init__(f"{label}: " + "; ".join(self.problems))


@dataclass(frozen=True)
class Column:
    """Una columna de una tabla.

    Attributes:
        kind: Tipo lógico: ``float``, ``int``, ``bool``, ``text`` o ``json``.
        nullable: Si admite valores vacíos.
    """

    kind: str
    nullable: bool = False


@dataclass(frozen=True)
class TableSpec:
    """Columnas y reglas de una tabla.

    Attributes:
        columns: Columnas, en el orden en que se guardan.
        exact: Si deben ser exactamente estas columnas (resultados) o al menos
            estas (datos de la sesión).
        enum: Columna cuyos valores deben estar en una enumeración del
            contrato, como ``("type", "incident_type")``.
        unique: Columnas que no pueden repetirse entre filas.
        max_rows: Máximo de filas, o ``None`` sin límite.
    """

    columns: Mapping[str, Column]
    exact: bool = True
    enum: tuple[str, str] | None = None
    unique: tuple[str, ...] = ()
    max_rows: int | None = None


_FLOAT = Column("float")
_FLOAT_NULL = Column("float", nullable=True)
_INT = Column("int")
_INT_NULL = Column("int", nullable=True)
_BOOL = Column("bool")
_BOOL_NULL = Column("bool", nullable=True)
_TEXT = Column("text")
_TEXT_NULL = Column("text", nullable=True)
_JSON = Column("json")
_JSON_NULL = Column("json", nullable=True)

SPECS: Mapping[str, TableSpec] = MappingProxyType(
    {
        # Resultados: se guardan en las tablas del mismo nombre.
        "episode": TableSpec(
            {
                "type": _TEXT,
                "t_start": _FLOAT,
                "t_end": _FLOAT,
                "screen": _TEXT_NULL,
                "outcome": _TEXT_NULL,
                "metrics": _JSON_NULL,
            },
            enum=("type", "episode_type"),
        ),
        "incident": TableSpec(
            {
                "type": _TEXT,
                "t": _FLOAT,
                "screen": _TEXT_NULL,
                "task_id": _INT_NULL,
                "element": _JSON_NULL,
            },
            enum=("type", "incident_type"),
        ),
        "task_result": TableSpec(
            {
                "task_id": _INT,
                "success": _BOOL,
                "duration_ms": _FLOAT,
                "steps": _INT,
                "deviation_step": _INT_NULL,
                "off_path_ms": _FLOAT_NULL,
            },
            unique=("task_id",),
        ),
        "usability_index": TableSpec(
            {
                "effectiveness": _FLOAT,
                "time_efficiency": _FLOAT,
                "path_efficiency": _FLOAT,
                "friction": _FLOAT,
                "bui": _FLOAT,
            },
            max_rows=1,
        ),
        # Mirada reprocesada al cerrar la sesión (analysis/gaze/refine.py).
        "gaze_refined": TableSpec(
            {
                "t": _FLOAT,
                "x": _FLOAT_NULL,
                "y": _FLOAT_NULL,
                "scroll_x": _FLOAT,
                "scroll_y": _FLOAT,
                "state": _TEXT,
                "confidence": _FLOAT,
                "valid": _BOOL,
                "zone": _TEXT_NULL,
                "element_selector": _TEXT_NULL,
                "fixation": _INT_NULL,
            },
            enum=("state", "gaze_state"),
        ),
        "gaze_quality": TableSpec(
            {
                "method": _TEXT,
                "fit_scope": _TEXT_NULL,
                "frames": _INT,
                "check_samples": _INT,
                "camera_delay_ms": _FLOAT,
                "live_error_deg": _FLOAT_NULL,
                "refined_error_deg": _FLOAT_NULL,
                "drift_corrected": _BOOL,
                "residual_lambda": _FLOAT_NULL,
                "noise_px": _FLOAT,
                "fixations": _INT,
            },
            max_rows=1,
        ),
        # Fijaciones atribuidas a los elementos de la pantalla (analysis/gaze/attention.py).
        "gaze_fixation": TableSpec(
            {
                "fixation": _INT,
                "t_start": _FLOAT,
                "t_end": _FLOAT,
                "x": _FLOAT,
                "y": _FLOAT,
                "scroll_x": _FLOAT,
                "scroll_y": _FLOAT,
                "screen": _TEXT_NULL,
                "sigma_px": _FLOAT,
                "element_selector": _TEXT_NULL,
                "element_p": _FLOAT_NULL,
                "resolved_selector": _TEXT_NULL,
                "resolved_p": _FLOAT_NULL,
                "ambiguous": _BOOL,
                "unassigned_p": _FLOAT,
                "attention_selector": _TEXT_NULL,
                "attention_p": _FLOAT_NULL,
                "long_stare": _BOOL,
            },
            unique=("fixation",),
        ),
        # Probabilidad de cada candidato de cada fijación; selector nulo es sin asignar.
        "gaze_attribution": TableSpec(
            {
                "fixation": _INT,
                "selector": _TEXT_NULL,
                "tag": _TEXT_NULL,
                "interactive": _BOOL_NULL,
                "p_gaze": _FLOAT,
                "p_attention": _FLOAT,
            },
        ),
        # Borradores: se actualizan por tarea y grabación, sin reemplazar confirmadas.
        "reference_draft": TableSpec(
            {
                "task_id": _INT,
                "steps": _JSON,
                "candidates": _JSON,
                "duration_ms": _FLOAT,
            },
            unique=("task_id",),
        ),
        # Datos de la sesión, tal como los entrega el repositorio.
        "events": TableSpec(
            {
                "t": _FLOAT,
                "type": _TEXT,
                "x": _FLOAT_NULL,
                "y": _FLOAT_NULL,
                "url": _TEXT,
                "title": _TEXT,
                # Pantalla: al cargar es la URL; la etapa de pantallas la normaliza.
                "screen": _TEXT,
                "task_id": _INT_NULL,
                "element": _JSON_NULL,
                "data": _JSON_NULL,
            },
            exact=False,
        ),
        "gaze": TableSpec(
            {
                "t": _FLOAT,
                "x": _FLOAT_NULL,
                "y": _FLOAT_NULL,
                "scroll_x": _FLOAT_NULL,
                "scroll_y": _FLOAT_NULL,
                "element_selector": _TEXT_NULL,
                "zone": _TEXT_NULL,
                "valid": _BOOL,
            },
            exact=False,
        ),
        "face": TableSpec(
            {
                "t": _FLOAT,
                "values": _JSON_NULL,
                "head_yaw": _FLOAT_NULL,
                "head_pitch": _FLOAT_NULL,
                "face_detected": _BOOL,
            },
            exact=False,
        ),
        "calibrations": TableSpec(
            {
                "t": _FLOAT,
                "type": _TEXT,
                "error_px": _FLOAT,
                "error_deg": _FLOAT,
                "accepted": _BOOL,
                "camera_delay_ms": _FLOAT_NULL,
            },
            exact=False,
        ),
        "tasks": TableSpec(
            {"task_id": _INT, "t_start": _FLOAT, "t_end": _FLOAT, "ended_by": _TEXT},
            exact=False,
        ),
        # Datos de la mirada (``GazeInputs``): cuadros, objetivos y disposiciones.
        "gaze_features": TableSpec(
            {
                "t": _FLOAT,
                "face_detected": _BOOL,
                **{
                    name: _FLOAT_NULL
                    for name in (
                        "head_yaw",
                        "head_pitch",
                        "head_roll",
                        "head_tx",
                        "head_ty",
                        "head_tz",
                        "distance_cm",
                        "eye_u",
                        "eye_v",
                        "aspect",
                        "left_h",
                        "left_v",
                        "left_open",
                        "right_h",
                        "right_v",
                        "right_open",
                        "blink",
                        "raw_x",
                        "raw_y",
                    )
                },
                "left_refined": _BOOL_NULL,
                "right_refined": _BOOL_NULL,
                "state": _TEXT,
                "confidence": _FLOAT,
                "viewport_width": _FLOAT,
                "viewport_height": _FLOAT,
                "scroll_x": _FLOAT,
                "scroll_y": _FLOAT,
            },
            exact=False,
            enum=("state", "gaze_state"),
        ),
        "gaze_targets": TableSpec(
            {
                "t": _FLOAT,
                "t_end": _FLOAT,
                "calibration_type": _TEXT,
                "phase": _TEXT,
                "group": _INT,
                "viewport_width": _FLOAT,
                "viewport_height": _FLOAT,
                "points": _JSON,
            },
            exact=False,
            enum=("phase", "gaze_target_phase"),
        ),
        "gaze_calibrations": TableSpec(
            {
                "t": _FLOAT,
                "type": _TEXT,
                "error_px": _FLOAT,
                "error_deg": _FLOAT,
                "accepted": _BOOL,
                "camera_delay_ms": _FLOAT_NULL,
                "estimator": _TEXT_NULL,
                "corrected": _BOOL_NULL,
                "correction_x_px": _FLOAT_NULL,
                "correction_y_px": _FLOAT_NULL,
            },
            exact=False,
            enum=("type", "calibration_type"),
        ),
        "layouts": TableSpec(
            {
                "t": _FLOAT,
                "screen": _JSON,
                "viewport_width": _FLOAT,
                "viewport_height": _FLOAT,
                "scroll_x": _FLOAT,
                "scroll_y": _FLOAT,
                "regions": _JSON,
                "elements": _JSON,
                "truncated": _BOOL,
            },
            exact=False,
        ),
        # Eventos que la atribución de la mirada usa: clics, focos y actividad.
        "gaze_interactions": TableSpec(
            {
                "t": _FLOAT,
                "type": _TEXT,
                "selector": _TEXT_NULL,
            },
            exact=False,
            enum=("type", "event_type"),
        ),
        "references": TableSpec(
            {
                "id": _INT,
                "task_id": _INT,
                "steps": _JSON,
                "end_condition": _JSON_NULL,
                "required_steps": _JSON,
                "duration_ms": _FLOAT_NULL,
            },
            exact=False,
        ),
    }
)
"""Especificación de cada tabla, por nombre."""

RESULT_TABLES = ("episode", "incident", "task_result", "usability_index")
"""Tablas de resultados, en el orden en que se guardan."""

GAZE_RESULT_TABLES = ("gaze_refined", "gaze_quality")
"""Tablas de la mirada reprocesada; se guardan aparte, con ``save_gaze_refinement``."""

GAZE_ATTENTION_TABLES = ("gaze_fixation", "gaze_attribution")
"""Tablas de la atribución de la mirada; se guardan aparte, con ``save_gaze_attention``."""


def spec(name: str) -> TableSpec:
    """Devuelve la especificación de una tabla.

    Args:
        name: Nombre de la tabla, una clave de ``SPECS``.

    Returns:
        Especificación de la tabla.

    Raises:
        KeyError: Si la tabla no existe.
    """
    try:
        return SPECS[name]
    except KeyError:
        raise KeyError(f"unknown table {name!r}; known tables: {sorted(SPECS)}") from None


def frame(name: str, records: Iterable[Mapping[str, Any]] = ()) -> pd.DataFrame:
    """Crea un DataFrame de una tabla con los tipos correctos.

    Es la forma recomendada de que una etapa arme su resultado: las claves de
    cada registro son las columnas, y una columna vacía que lo admite puede
    omitirse.

    Args:
        name: Nombre de la tabla.
        records: Filas, como diccionarios.

    Returns:
        DataFrame con las columnas de la tabla, en orden.

    Raises:
        ColumnValidationError: Si un registro tiene una columna desconocida (en
            las tablas de resultados) o le falta un valor obligatorio.
    """
    table = spec(name)
    rows = list(records)
    problems = []
    if table.exact:
        unknown = sorted({key for row in rows for key in row} - table.columns.keys())
        if unknown:
            problems.append(f"unknown columns {unknown}")
    for column_name, column in table.columns.items():
        if not column.nullable and any(is_missing(row.get(column_name)) for row in rows):
            problems.append(f"column {column_name!r} is required")
    if problems:
        raise ColumnValidationError(name, name, problems)
    return pd.DataFrame(
        {
            column_name: pd.Series(
                [row.get(column_name) for row in rows], dtype=_dtype(column), name=column_name
            )
            for column_name, column in table.columns.items()
        }
    )


def empty(name: str) -> pd.DataFrame:
    """Crea un DataFrame vacío de una tabla, con sus columnas y tipos.

    Args:
        name: Nombre de la tabla.

    Returns:
        DataFrame sin filas.
    """
    return frame(name)


def validate(df: Any, name: str, *, label: str | None = None) -> None:
    """Comprueba que un DataFrame cumpla la especificación de su tabla.

    Revisa columnas faltantes o sobrantes, tipos, vacíos en columnas
    obligatorias, valores de enumeración, repetidos y cantidad de filas. En un
    DataFrame sin filas no revisa los tipos.

    Args:
        df: DataFrame a comprobar.
        name: Nombre de la tabla.
        label: Qué lo produjo, para el mensaje (por defecto, la tabla).

    Raises:
        ColumnValidationError: Con todos los problemas encontrados.
    """
    table = spec(name)
    label = label or name
    if not isinstance(df, pd.DataFrame):
        raise ColumnValidationError(label, name, [f"expected a DataFrame, got {type(df).__name__}"])
    problems = []
    missing = [column for column in table.columns if column not in df.columns]
    if missing:
        problems.append(f"missing columns {missing}")
    if table.exact:
        extra = [column for column in df.columns if column not in table.columns]
        if extra:
            problems.append(f"unexpected columns {extra}")
    for column_name, column in table.columns.items():
        if column_name in df.columns:
            problems.extend(_check_column(df[column_name], column_name, column))
    problems.extend(_check_rows(df, table))
    if problems:
        raise ColumnValidationError(label, name, problems)


def concat(name: str, frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Une DataFrames ya validados de una misma tabla.

    Args:
        name: Nombre de la tabla.
        frames: DataFrames a unir; los vacíos se ignoran.

    Returns:
        Un solo DataFrame con las columnas de la tabla, o uno vacío si no hay filas.
    """
    filled = [df for df in frames if len(df) > 0]
    if not filled:
        return empty(name)
    return pd.concat(filled, ignore_index=True)[list(spec(name).columns)]


def _dtype(column: Column) -> str:
    """Tipo de pandas de una columna."""
    if column.kind == "bool":
        return "boolean" if column.nullable else "bool"
    return {"float": "float64", "int": "Int64"}.get(column.kind, "object")


def is_missing(value: Any) -> bool:
    """Indica si un valor está vacío.

    Args:
        value: Valor de una celda.

    Returns:
        ``True`` para ``None``, ``NaN`` y ``NA``; ``False`` para cualquier otro
        valor, incluidos diccionarios y listas.
    """
    if isinstance(value, dict | list | tuple):
        return False
    return bool(pd.isna(value))


def _check_column(series: pd.Series, name: str, column: Column) -> list[str]:
    """Problemas de tipo y de vacíos de una columna."""
    problems = []
    values = series.dropna()
    if column.kind == "float":
        type_ok = ptypes.is_numeric_dtype(series) and not ptypes.is_bool_dtype(series)
    elif column.kind == "int":
        type_ok = ptypes.is_integer_dtype(series)
    elif column.kind == "bool":
        type_ok = ptypes.is_bool_dtype(series)
    elif column.kind == "text":
        type_ok = (ptypes.is_string_dtype(series) or ptypes.is_object_dtype(series)) and all(
            isinstance(value, str) for value in values
        )
    else:
        type_ok = ptypes.is_object_dtype(series) and all(
            isinstance(value, dict | list) for value in values
        )
    if len(series) > 0 and not type_ok:
        hint = " (use Int64 for integers with empty values)" if column.kind == "int" else ""
        problems.append(f"column {name!r} must be {column.kind}, got {series.dtype}{hint}")
    if not column.nullable and series.isna().any():
        problems.append(f"column {name!r} has empty values")
    return problems


def _check_rows(df: pd.DataFrame, table: TableSpec) -> list[str]:
    """Problemas de enumeración, repetidos y cantidad de filas."""
    problems = []
    if table.enum and table.enum[0] in df.columns:
        column, enum_name = table.enum
        unknown = sorted(set(df[column].dropna()) - set(contracts.enums()[enum_name]))
        if unknown:
            problems.append(f"column {column!r} has values not in {enum_name}: {unknown}")
    present = [column for column in table.unique if column in df.columns]
    if present and df.duplicated(subset=present).any():
        problems.append(f"repeated values in {present}")
    if table.max_rows is not None and len(df) > table.max_rows:
        problems.append(f"expected at most {table.max_rows} row(s), got {len(df)}")
    return problems
