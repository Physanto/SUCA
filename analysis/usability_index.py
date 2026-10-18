"""Etapa 6 del análisis: índice de usabilidad conductual (``bui``).

Qué hará, en las sesiones guiadas, a partir de los resultados por tarea y de
los incidentes (cada componente de 0 a 100):

- ``effectiveness``: tareas completadas sobre tareas asignadas;
- ``time_efficiency``: promedio de ``min(1, t_ref / t_usuario)`` sobre las
  tareas completadas;
- ``path_efficiency``: lo mismo con los pasos;
- ``friction``: ``1 - min(1, i / params.friction_i_max)``, con ``i`` los
  incidentes por minuto de tarea;
- ``bui``: promedio de los cuatro componentes.

Si no se completó ninguna tarea, las dos eficiencias valen 0. En el modo libre
no se calcula el índice. La versión de los parámetros la agrega el repositorio
al guardar.

Esqueleto: por ahora devuelve un DataFrame vacío con las columnas correctas.
"""

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters


def compute(
    data: SessionData, task_results: pd.DataFrame, incidents: pd.DataFrame, params: Parameters
) -> pd.DataFrame:
    """Calcula el índice de una sesión.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        task_results: Resultados por tarea (tabla ``task_result``).
        incidents: Incidentes de la sesión (tabla ``incident``).
        params: Parámetros del análisis.

    Returns:
        Una fila con las columnas de ``usability_index``, o ninguna si la sesión
        no es guiada o no se puede calcular.
    """
    return columns.empty("usability_index")
