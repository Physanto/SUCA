"""Mirada: medición en grados, reprocesamiento al cerrar la sesión y atribución.

- ``model``: el estimador geométrico de la extensión, en numpy.
- ``samples``: cuadros (``gaze_feature``) junto con el punto que debían mirar
  (``gaze_target``).
- ``bench``: banco de pruebas: error de la mirada en grados, por fase, región de
  la pantalla, postura de la cabeza y a lo largo del tiempo.
- ``refine``: vuelve a estimar la mirada con toda la sesión a la vista.
- ``layout``: zona y elemento de un punto, con la disposición registrada.
"""

import math
from dataclasses import dataclass, replace

import pandas as pd

from analysis.parameters import GazeParams
from shared.config import CameraConfig


@dataclass(frozen=True)
class GazeSettings:
    """Lo que la medición y el reprocesamiento necesitan de la configuración.

    Attributes:
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.
        viewing_distance_cm: Distancia de referencia, si un cuadro no la trae.
        blink_threshold: Parpadeo desde el que un cuadro se descarta.
        params: Umbrales de ``gaze`` en ``analysis/parameters.yaml``.
    """

    css_px_per_cm: float
    viewing_distance_cm: float
    blink_threshold: float
    params: GazeParams

    @classmethod
    def from_config(cls, camera: CameraConfig, params: GazeParams) -> "GazeSettings":
        """Arma los ajustes con la sección ``camera`` de la configuración y los parámetros.

        Args:
            camera: Configuración de la cámara.
            params: Parámetros de la mirada.

        Returns:
            Ajustes.
        """
        return cls(
            css_px_per_cm=camera.css_px_per_cm,
            viewing_distance_cm=camera.viewing_distance_cm,
            blink_threshold=camera.blink_threshold,
            params=params,
        )

    def for_session(self, calibrations: pd.DataFrame) -> "GazeSettings":
        """Ajustes con la pantalla y la distancia que registró la sesión.

        Cada equipo puede tener su pantalla (opciones de la extensión): la
        calibración guarda los píxeles por centímetro con que trabajó, y esos
        mandan sobre la configuración. La distancia de referencia pasa a ser la
        mediana de las medidas en la sesión. Sin esos datos (sesiones
        anteriores), quedan los de la configuración.

        Args:
            calibrations: Filas de ``calibration`` de la sesión (``t``, ``type`` y,
                si existen, ``css_px_per_cm`` y ``viewing_distance_cm``).

        Returns:
            Ajustes de la sesión.
        """
        changes: dict[str, float] = {}
        if "css_px_per_cm" in calibrations:
            screens = calibrations.sort_values("t")["css_px_per_cm"].astype(float).dropna()
            screens = screens[screens > 0]
            if len(screens):
                # La última calibración manda: si se cambió la pantalla, se recalibró.
                changes["css_px_per_cm"] = float(screens.iloc[-1])
        if "viewing_distance_cm" in calibrations:
            distances = calibrations["viewing_distance_cm"].astype(float).dropna()
            distances = distances[distances > 0]
            if len(distances) and math.isfinite(float(distances.median())):
                changes["viewing_distance_cm"] = float(distances.median())
        return replace(self, **changes) if changes else self
