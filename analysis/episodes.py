"""Etapa 3 del análisis: segmentación de la sesión en episodios.

Cada tipo de episodio (inicio de sesión, formulario, búsqueda, pantalla) lo
reconoce un detector de episodios registrado en ``EPISODE_DETECTORS``.
``detect`` los ejecuta todos, valida lo que devuelve cada uno y une los
episodios. Agregar un detector de episodios no cambia ``detect`` ni el
orquestador.

Cómo agregar un detector de episodios
-------------------------------------

1. Elige su tipo en la enumeración ``episode_type`` de ``contracts/enums.json``.
2. Escribe una clase con el atributo ``episode_type`` y el método ``find``, y
   regístrala con ``@EPISODE_DETECTORS.register``::

       @EPISODE_DETECTORS.register
       class ScreenEpisodes:
           # Un episodio por cada visita a una pantalla.
           episode_type = "screen"

           def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
               rows = []
               ...  # recorrer data.events agrupando por la columna screen
               return columns.frame("episode", rows)

3. ``find`` devuelve un DataFrame con las columnas de la tabla ``episode``
   (``type``, ``t_start``, ``t_end``, ``screen``, ``outcome``, ``metrics``),
   todas con ``type`` igual a su ``episode_type``. ``metrics`` es un
   diccionario con las métricas propias del tipo. Sin episodios, devuelve
   ``columns.empty("episode")``.
4. Lee los umbrales de ``params``, nunca escritos en el código.
5. Prueba el detector con un caso que debe reconocer y uno que no.

Un detector no modifica ``data``. Si falla o devuelve columnas incorrectas, la
etapa se detiene con un error que lo nombra.
"""

from typing import Protocol

import pandas as pd

from analysis import columns
from analysis.loader import SessionData
from analysis.parameters import Parameters
from analysis.registry import Registry
from shared import contracts


class EpisodeDetector(Protocol):
    """Interfaz de un detector de episodios.

    Attributes:
        episode_type: Tipo de episodio que reconoce (``episode_type``).
    """

    episode_type: str

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Reconoce los episodios de su tipo en una sesión.

        Args:
            data: Datos de la sesión, limpios y con pantallas.
            params: Parámetros del análisis.

        Returns:
            DataFrame con las columnas de ``episode``; vacío si no hay ninguno.
        """
        ...


EPISODE_DETECTORS: Registry[EpisodeDetector] = Registry(
    "episode detector", key="episode_type", allowed=contracts.enums()["episode_type"]
)
"""Detectores de episodios registrados. Esqueleto: todavía ninguno."""


def detect(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Ejecuta todos los detectores de episodios registrados y une sus episodios.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        params: Parámetros del análisis.

    Returns:
        Episodios de todos los detectores, ordenados por inicio, con las
        columnas de ``episode``. Vacío si no hay detectores o episodios.

    Raises:
        RuntimeError: Si un detector falla; el mensaje lo nombra.
        columns.ColumnValidationError: Si un detector devuelve columnas,
            tipos o un ``type`` incorrectos.
    """
    found = []
    for detector in EPISODE_DETECTORS.all():
        label = f"episode detector {detector.episode_type}"
        try:
            result = detector.find(data, params)
        except Exception as error:
            raise RuntimeError(f"{label} failed: {error}") from error
        columns.validate(result, "episode", label=label)
        other_types = sorted(set(result["type"]) - {detector.episode_type})
        if other_types:
            raise columns.ColumnValidationError(
                label, "episode", [f"returned episodes of other types: {other_types}"]
            )
        found.append(result)
    return columns.concat("episode", found).sort_values("t_start", kind="stable", ignore_index=True)
