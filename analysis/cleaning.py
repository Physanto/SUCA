"""Etapa 1 del análisis: limpieza de los datos de la sesión.

Operaciones:

- ordenar los eventos, la mirada y el rostro por tiempo;
- quitar los registros duplicados. Llegan cuando Chrome detiene el service
  worker durante una entrega y un lote se envía dos veces; las copias son
  idénticas, con el mismo ``t``;
- restar ``params.camera_delay_ms`` al tiempo de la mirada y del rostro, para
  alinearlos con los eventos.

"""

import json
from dataclasses import replace
from typing import Any

import pandas as pd

from analysis.loader import SessionData
from analysis.parameters import Parameters


def clean(data: SessionData, params: Parameters) -> SessionData:
    """Limpia los datos de una sesión.

    Args:
        data: Datos de la sesión, como los entrega el repositorio.
        params: Parámetros del análisis.

    Returns:
        Datos limpios, con las mismas columnas base. Si cambia algo, una copia
        (``dataclasses.replace``); nunca modifica ``data``.
    """
    return replace(
        data,
        events=_clean_frame(data.events),
        gaze=_clean_frame(data.gaze, params.camera_delay_ms),
        face=_clean_frame(data.face, params.camera_delay_ms),
    )


def _clean_frame(frame: pd.DataFrame, delay_ms: float = 0) -> pd.DataFrame:
    """Quita copias exactas, corrige el reloj y ordena sin modificar la entrada."""
    keys = frame.copy()
    for name in keys.select_dtypes(include="object"):
        keys[name] = keys[name].map(_duplicate_key)
    cleaned = frame.loc[~keys.duplicated()].copy()
    if delay_ms:
        cleaned["t"] = cleaned["t"] - delay_ms
    return cleaned.sort_values("t", kind="stable", ignore_index=True)


def _duplicate_key(value: Any) -> Any:
    """Compara campos JSON anidados sin depender del orden de sus claves."""
    if isinstance(value, dict | list):
        return (json.dumps(value, sort_keys=True),)
    return value
