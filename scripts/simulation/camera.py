"""Cámara simulada: ojos con un modelo geométrico conocido, calibración y rostro.

Un modelo geométrico verdadero (el mismo de las pruebas de la extensión) da,
para cada punto de la pantalla y cada postura de la cabeza, la posición del
iris que tendría la persona. Con él se arman los registros que la extensión
enviaría: las características de cada cuadro (lote ``gaze_features``), los
objetivos de la calibración (``gaze_target``, con los 10 s de rostro relajado
al empezar) y su resultado (``calibration``). El rostro da los valores del
contrato ``face_value`` con más tensión cuando se le pide.

Así el reprocesamiento de la mirada, la atribución a elementos y el análisis
facial corren sobre los datos simulados igual que sobre los reales.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

TRUTH = np.array([-2.2, 0.04, -2.8, -0.05, 0.6, 1, 1, 650, -90, 1.05, 0.97])
"""Parámetros verdaderos del modelo geométrico de la persona simulada."""

OPEN_REF = 0.3
"""Apertura de los ojos de referencia del modelo."""

CSS_PX_PER_CM = 40.0
"""Densidad de la pantalla simulada, en píxeles CSS por centímetro."""

FRAME_MS = 33.0
"""Separación de los cuadros durante la calibración (unos 30 por segundo)."""

DELAY_MS = 70.0
"""Retraso verdadero de la cámara: cada cuadro muestra el ojo de 70 ms antes."""

CALIBRATION_POSE = {"yaw": 0.0, "pitch": -8.0, "distance": 58.0}
"""Postura de la cabeza durante la calibración."""

SESSION_POSE = {"yaw": 2.0, "pitch": -10.0, "distance": 60.0}
"""Postura durante el uso: algo distinta de la calibrada, como en una sesión real."""

NEUTRAL_BASELINE_MS = 10_000.0
"""Duración de la línea base de rostro relajado, como en la extensión."""

LIVE_NOISE_PX = 25.0
"""Ruido de la mirada en vivo respecto del punto mirado, en píxeles."""

FACE_VALUES = (
    "brow_down_left",
    "brow_down_right",
    "brow_inner_up",
    "eye_squint_left",
    "eye_squint_right",
    "eye_blink_left",
    "eye_blink_right",
    "mouth_press_left",
    "mouth_press_right",
    "mouth_frown_left",
    "mouth_frown_right",
    "mouth_smile_left",
    "mouth_smile_right",
)
"""Valores faciales del contrato (``face_value`` de ``contracts/enums.json``)."""

_RAD = np.pi / 180
_STILL = (2.0, 2.0, 2.0)
_POINTS = (0.1, 0.5, 0.9)
_INNER = (0.3, 0.7)
_VALIDATION = (
    (0.2, 0.2),
    (0.8, 0.2),
    (0.2, 0.8),
    (0.8, 0.8),
    (0.5, 0.3),
    (0.5, 0.7),
    (0.3, 0.5),
    (0.7, 0.5),
)


def iris_for(x: float, y: float, pose: dict[str, float]) -> tuple[float, float]:
    """Posición del iris (``h``, ``v``) que hace mirar un punto con una postura dada.

    Args:
        x: Punto mirado, en píxeles CSS de la ventana.
        y: Punto mirado, en píxeles CSS de la ventana.
        pose: Postura completa (``yaw``, ``pitch``, ``distance``, ``eye_u``,
            ``eye_v``, ``aspect`` y ``open``).

    Returns:
        Ángulos del iris horizontal y vertical.
    """
    a_h, b_h, a_v, b_v, c_open, g_yaw, g_pitch, cx, cy, kx, ky = TRUTH
    tan_v = np.tan(63 * _RAD / 2)
    tan_h = tan_v * pose["aspect"]
    oz = pose["distance"]
    ox = -(pose["eye_u"] - 0.5) * 2 * tan_h * oz
    oy = (pose["eye_v"] - 0.5) * 2 * tan_v * oz
    px = (x - cx) / (kx * CSS_PX_PER_CM)
    py = (y - cy) / (ky * CSS_PX_PER_CM)
    yaw = np.arctan((px - ox) / oz)
    pitch = np.arctan((oy - py) * np.cos(yaw) / oz)
    theta = yaw - g_yaw * pose["yaw"] * _RAD
    phi = pitch - g_pitch * pose["pitch"] * _RAD
    return (theta - b_h) / a_h, (phi - b_v - c_open * (pose["open"] - OPEN_REF)) / a_v


@dataclass
class CalibrationRun:
    """Registros de una calibración simulada.

    Attributes:
        start: Inicio, en ms desde 1970.
        end: Fin; la sesión sigue desde aquí.
        frames: Cuadros de ``gaze_features`` del procedimiento.
        targets: Objetivos de ``gaze_target``, en orden.
        record: Resultado para el lote ``calibration``.
    """

    start: float
    end: float
    frames: list[dict[str, Any]] = field(default_factory=list)
    targets: list[dict[str, Any]] = field(default_factory=list)
    record: dict[str, Any] = field(default_factory=dict)


class SimulatedEyes:
    """Ojos y cabeza de la persona simulada, con su propio azar.

    Args:
        seed: Semilla: la misma produce los mismos cuadros.
        viewport: Ancho y alto de la ventana, en píxeles CSS.
    """

    def __init__(self, seed: int, viewport: tuple[float, float]) -> None:
        """Prepara la persona con su azar."""
        self._random = np.random.default_rng(seed)
        self.viewport = (float(viewport[0]), float(viewport[1]))

    def pose(
        self, center: dict[str, float], spread: tuple[float, float, float] = _STILL
    ) -> dict[str, float]:
        """Postura al azar alrededor de una postura central."""

        def jitter(radius: float) -> float:
            return float(self._random.uniform(-radius, radius))

        return {
            "yaw": center["yaw"] + jitter(spread[0]),
            "pitch": center["pitch"] + jitter(spread[1]),
            "distance": center["distance"] + jitter(spread[2]),
            "eye_u": 0.5 + jitter(0.06),
            "eye_v": 0.45 + jitter(0.05),
            "aspect": 16 / 9,
            "open": OPEN_REF + jitter(0.02),
        }

    def frame(
        self,
        t: float,
        look: tuple[float, float],
        pose: dict[str, float],
        *,
        state: str = "on_screen",
        blink: float = 0.02,
        scroll_y: float = 0.0,
    ) -> dict[str, Any]:
        """Un cuadro de ``gaze_features`` que mira un punto de la ventana.

        Args:
            t: Momento del cuadro.
            look: Punto mirado, en la ventana.
            pose: Postura de la cabeza.
            state: Estado de la mirada según el monitor.
            blink: Valor de parpadeo.
            scroll_y: Scroll vertical de la página.

        Returns:
            Registro con la forma del contrato.
        """
        h, v = iris_for(look[0], look[1], pose)

        def noise() -> float:
            return float(self._random.normal(0, 0.0015))

        return {
            "t": round(t, 1),
            "face_detected": True,
            "head_yaw": round(pose["yaw"], 3),
            "head_pitch": round(pose["pitch"], 3),
            "head_roll": 0.0,
            "head_tx": 0.0,
            "head_ty": 0.0,
            "head_tz": round(-pose["distance"], 3),
            "distance_cm": round(pose["distance"], 3),
            "eye_u": round(pose["eye_u"], 4),
            "eye_v": round(pose["eye_v"], 4),
            "aspect": round(pose["aspect"], 4),
            "left_h": float(h) + noise(),
            "left_v": float(v) + noise(),
            "left_open": round(pose["open"], 4),
            "left_refined": True,
            "right_h": float(h) + noise(),
            "right_v": float(v) + noise(),
            "right_open": round(pose["open"], 4),
            "right_refined": True,
            "blink": blink,
            "state": state,
            "confidence": 1.0,
            "raw_x": round(look[0] + float(self._random.normal(0, LIVE_NOISE_PX)), 1),
            "raw_y": round(look[1] + float(self._random.normal(0, LIVE_NOISE_PX)), 1),
            "viewport_width": self.viewport[0],
            "viewport_height": self.viewport[1],
            "scroll_x": 0.0,
            "scroll_y": scroll_y,
        }

    def calibration(
        self, kind: str, start: float, error_deg: float, accepted: bool
    ) -> CalibrationRun:
        """Procedimiento completo de una calibración, como el de la extensión.

        La inicial empieza con 10 s de rostro relajado mirando el centro
        (sin cuadros de mirada: la mirada está en pausa), sigue con 13 puntos,
        el punto en movimiento, el movimiento de cabeza, 8 puntos de validación
        y la vuelta del teclado. La final solo valida.

        Args:
            kind: ``initial`` o ``final``.
            start: Inicio, en ms desde 1970.
            error_deg: Error medio que informa la calibración.
            accepted: Si se aceptó.

        Returns:
            Cuadros, objetivos y resultado.
        """
        run = CalibrationRun(start=start, end=start)
        width, height = self.viewport
        center = (width / 2, height / 2)
        if kind == "initial":
            run.targets.append(
                self._target(
                    kind, "neutral_baseline", 0, run.end, run.end + NEUTRAL_BASELINE_MS, [center]
                )
            )
            run.end += NEUTRAL_BASELINE_MS + 400
            grid = [(fx * width, fy * height) for fy in _POINTS for fx in _POINTS]
            grid += [(fx * width, fy * height) for fy in _INNER for fx in _INNER]
            for group, point in enumerate(grid):
                self._fixed(run, kind, "points", group, point, _STILL, 1100)
            self._pursuit(run, 12_000)
            self._fixed(run, kind, "head", 0, center, (12, 10, 8), 8000)
        for group, (fx, fy) in enumerate(_VALIDATION):
            self._fixed(run, kind, "validation", group, (fx * width, fy * height), _STILL, 1000)
        if kind == "initial":
            # Mira el teclado (fuera de la pantalla) y vuelve al punto.
            for _ in range(40):
                pose = self.pose({"yaw": 0.0, "pitch": -30.0, "distance": 58.0})
                run.frames.append(
                    self.frame(run.end, (center[0], height * 1.8), pose, state="off_screen")
                )
                run.end += FRAME_MS
            self._fixed(run, kind, "look_away", 0, (center[0], height * 0.45), _STILL, 1000)
        run.record = {
            "t": round(run.end, 1),
            "type": kind,
            "error_px": round(error_deg * self._px_per_deg(), 1),
            "error_deg": error_deg,
            "accepted": accepted,
            "css_px_per_cm": CSS_PX_PER_CM,
            "viewing_distance_cm": CALIBRATION_POSE["distance"],
            "estimator": "geometric",
            "camera_delay_ms": DELAY_MS if kind == "initial" else None,
        }
        return run

    def _px_per_deg(self) -> float:
        """Píxeles por grado a la distancia de la calibración."""
        return CSS_PX_PER_CM * CALIBRATION_POSE["distance"] * float(np.tan(_RAD))

    def _fixed(
        self,
        run: CalibrationRun,
        kind: str,
        phase: str,
        group: int,
        point: tuple[float, float],
        spread: tuple[float, float, float],
        duration_ms: float,
    ) -> None:
        """Un objetivo fijo mirado durante un tramo, con una pausa después."""
        begin = run.end
        while run.end < begin + duration_ms:
            run.frames.append(self.frame(run.end, point, self.pose(CALIBRATION_POSE, spread)))
            run.end += FRAME_MS
        run.targets.append(self._target(kind, phase, group, begin, run.end, [point]))
        run.end += 400

    def _pursuit(self, run: CalibrationRun, duration_ms: float) -> None:
        """Punto en movimiento: cada cuadro muestra el ojo de ``DELAY_MS`` antes."""
        begin = run.end
        width, height = self.viewport

        def position(t: float) -> tuple[float, float]:
            s = (t - begin) / 1000
            return (
                width * (0.5 + 0.4 * float(np.sin(2 * np.pi * 0.15 * s))),
                height * (0.5 + 0.4 * float(np.sin(2 * np.pi * 0.2 * s))),
            )

        while run.end < begin + duration_ms:
            pose = self.pose(CALIBRATION_POSE)
            run.frames.append(self.frame(run.end, position(run.end - DELAY_MS), pose))
            run.end += FRAME_MS
        path = [position(t) for t in np.arange(begin, begin + duration_ms, 16.0)]
        times = list(np.arange(begin, begin + duration_ms, 16.0))
        target = self._target("initial", "pursuit", 0, begin, run.end, path)
        target["points"] = [
            {"t": round(float(t), 1), "x": round(x, 1), "y": round(y, 1)}
            for t, (x, y) in zip(times, path, strict=True)
        ]
        run.targets.append(target)
        run.end += 400

    def _target(
        self,
        kind: str,
        phase: str,
        group: int,
        begin: float,
        end: float,
        points: Sequence[tuple[float, float]],
    ) -> dict[str, Any]:
        """Objetivo de ``gaze_target`` con la forma del contrato."""
        return {
            "t_start": round(begin, 1),
            "t_end": round(end, 1),
            "calibration_type": kind,
            "phase": phase,
            "group": group,
            "viewport_width": self.viewport[0],
            "viewport_height": self.viewport[1],
            "points": [
                {"t": round(begin, 1), "x": round(x, 1), "y": round(y, 1)} for x, y in points
            ],
        }


def face_values(random: Any, tension: float) -> dict[str, float]:
    """Valores faciales de un cuadro, con la tensión pedida.

    La tensión sube el descenso de cejas, la presión de labios y el
    entrecerrar los ojos, y baja la sonrisa. Con tensión 0 el rostro está
    relajado, como en la línea base.

    Args:
        random: Generador con ``uniform`` (``random.Random``).
        tension: Entre 0 y 1.

    Returns:
        Valor de cada ``face_value`` del contrato, entre 0 y 1.
    """
    blink = 0.9 if random.uniform(0, 1) < 0.04 else random.uniform(0, 0.1)
    values = {
        "brow_down_left": tension + random.uniform(0, 0.15),
        "brow_down_right": tension + random.uniform(0, 0.15),
        "brow_inner_up": random.uniform(0, 0.2),
        "eye_squint_left": tension * 0.5 + random.uniform(0, 0.15),
        "eye_squint_right": tension * 0.5 + random.uniform(0, 0.15),
        "eye_blink_left": blink,
        "eye_blink_right": blink,
        "mouth_press_left": tension * 0.8 + random.uniform(0, 0.1),
        "mouth_press_right": tension * 0.8 + random.uniform(0, 0.1),
        "mouth_frown_left": tension * 0.3 + random.uniform(0, 0.05),
        "mouth_frown_right": tension * 0.3 + random.uniform(0, 0.05),
        "mouth_smile_left": (0.3 - tension / 2) * random.uniform(0.2, 1),
        "mouth_smile_right": (0.3 - tension / 2) * random.uniform(0.2, 1),
    }
    return {key: round(min(max(values[key], 0.0), 1.0), 3) for key in FACE_VALUES}
