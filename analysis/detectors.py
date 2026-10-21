"""Etapa 4 del análisis: detectores de incidentes de fricción.

Cada detector es una estrategia registrada en ``DETECTORS``. ``detect`` los
ejecuta todos, valida lo que devuelve cada uno y une los incidentes. Agregar
un detector no cambia ``detect`` ni el orquestador.

Cómo agregar un detector
------------------------

1. Elige su tipo en la enumeración ``incident_type`` de ``contracts/enums.json``
   (si falta, pídelo: los tipos los define el contrato).
2. Escribe una clase con el atributo ``incident_type`` y el método ``find``, y
   regístrala con ``@DETECTORS.register``::

       @DETECTORS.register
       class DeadClickDetector:
           # Clic sin cambios en la página ni navegación en el tiempo de espera.
           incident_type = "dead_click"

           def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
               rows = []
               ...  # recorrer data.events con params.dead_click.wait_ms
               return columns.frame("incident", rows)

3. ``find`` devuelve un DataFrame con las columnas de la tabla ``incident``
   (``type``, ``t``, ``screen``, ``task_id``, ``element``), una fila por
   incidente, todas con ``type`` igual a su ``incident_type``. Sin incidentes,
   devuelve ``columns.empty("incident")``. ``columns.frame`` arma el DataFrame
   con los tipos correctos.
4. Lee los umbrales de ``params`` (``parameters.yaml``), nunca escritos en el código.
5. Prueba el detector con un caso que debe detectar y uno que no.

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


class Detector(Protocol):
    """Interfaz de un detector de incidentes.

    Attributes:
        incident_type: Tipo de incidente que produce (``incident_type``).
    """

    incident_type: str

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Busca los incidentes de su tipo en una sesión.

        Args:
            data: Datos de la sesión, limpios y con pantallas.
            params: Parámetros del análisis.

        Returns:
            DataFrame con las columnas de ``incident``; vacío si no hay ninguno.
        """
        ...


DETECTORS: Registry[Detector] = Registry(
    "detector", key="incident_type", allowed=contracts.enums()["incident_type"]
)
"""Detectores registrados. Esqueleto: todavía ninguno."""


def detect(data: SessionData, params: Parameters) -> pd.DataFrame:
    """Ejecuta todos los detectores registrados y une sus incidentes.

    Args:
        data: Datos de la sesión, limpios y con pantallas.
        params: Parámetros del análisis.

    Returns:
        Incidentes de todos los detectores, ordenados por tiempo, con las
        columnas de ``incident``. Vacío si no hay detectores o incidentes.

    Raises:
        RuntimeError: Si un detector falla; el mensaje lo nombra.
        columns.ColumnValidationError: Si un detector devuelve columnas,
            tipos o un ``type`` incorrectos.
    """
    found = []
    for detector in DETECTORS.all():
        label = f"detector {detector.incident_type}"
        try:
            result = detector.find(data, params)
        except Exception as error:
            raise RuntimeError(f"{label} failed: {error}") from error
        columns.validate(result, "incident", label=label)
        other_types = sorted(set(result["type"]) - {detector.incident_type})
        if other_types:
            raise columns.ColumnValidationError(
                label, "incident", [f"returned incidents of other types: {other_types}"]
            )
        found.append(result)
    return columns.concat("incident", found).sort_values("t", kind="stable", ignore_index=True)
