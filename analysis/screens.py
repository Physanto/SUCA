"""Etapa 2 del análisis: identificación de las pantallas.

Qué hará: normalizar la columna ``screen`` de ``data.events``, que al cargar es
la URL de cada evento:

- quitar identificadores numéricos y parámetros variables (``/order/8812`` →
  ``/order/{id}``);
- en aplicaciones de una sola página, tratar cada ruta como una pantalla;
- si dos pantallas comparten URL, distinguirlas por el título (``title``).

``url`` y ``title`` se conservan tal como se capturaron. Las etapas siguientes
agrupan por ``screen``.

Esqueleto: por ahora devuelve los datos sin cambios (``screen`` = URL).
"""

from analysis.loader import SessionData
from analysis.parameters import Parameters


def assign_screens(data: SessionData, params: Parameters) -> SessionData:
    """Asigna a cada evento su pantalla normalizada.

    Args:
        data: Datos de la sesión, ya limpios.
        params: Parámetros del análisis.

    Returns:
        Datos con ``events.screen`` normalizado. Si cambia algo, una copia
        (``dataclasses.replace``); nunca modifica ``data``.
    """
    return data
