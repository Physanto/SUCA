"""Mirada: medición en grados y reprocesamiento al cerrar la sesión.

- ``model``: el estimador geométrico de la extensión, en numpy.
- ``samples``: cuadros (``gaze_feature``) junto con el punto que debían mirar
  (``gaze_target``).
- ``bench``: banco de pruebas: error de la mirada en grados, por fase, región de
  la pantalla, postura de la cabeza y a lo largo del tiempo.
- ``refine``: vuelve a estimar la mirada con toda la sesión a la vista.
- ``layout``: zona y elemento de un punto, con la disposición registrada.
"""

from dataclasses import dataclass

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
