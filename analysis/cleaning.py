"""Etapa 1 del análisis: limpieza de los datos de la sesión.

Qué hará:

- ordenar los eventos, la mirada y el rostro por tiempo;
- quitar los registros duplicados. Llegan cuando Chrome detiene el service
  worker durante una entrega y un lote se envía dos veces; las copias son
  idénticas, con el mismo ``t``;
- restar ``params.camera_delay_ms`` al tiempo de la mirada y del rostro, para
  alinearlos con los eventos.

Esqueleto: por ahora devuelve los datos sin cambios.
"""

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
    return data
