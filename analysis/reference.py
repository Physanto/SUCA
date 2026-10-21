"""Etapa 5 del análisis: comparación con las referencias.

Qué hará, para cada tarea de una sesión guiada (``data.tasks``):

- alinear los pasos del participante con los de cada referencia confirmada
  (``data.references``) por pantalla, texto y rol del elemento;
- decidir el éxito: la tarea llegó a la condición final y cumplió los pasos
  obligatorios (``required_steps``);
- contar los pasos, el punto de desvío (primer paso que no coincide con el
  siguiente esperado de ninguna referencia) y el tiempo fuera de ruta.

Las sesiones que no son guiadas no tienen resultados por tarea.

Esqueleto: por ahora devuelve un DataFrame vacío con las columnas correctas.
"""

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters


def compare(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Compara cada tarea de la sesión con sus referencias.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        params: Parámetros del análisis.

    Returns:
        Una fila por tarea, con las columnas de ``task_result``; vacío si la
        sesión no es guiada.
    """
    return columns.empty("task_result")
