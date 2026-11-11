"""Sesión de mirada simulada, con una persona de parámetros conocidos.

Un modelo geométrico verdadero (el mismo de las pruebas de la extensión) da,
para cada punto de la pantalla y cada postura de la cabeza, la posición del
iris que tendría la persona. Con eso se arma una sesión completa como la
guardaría el servidor: calibración inicial (13 puntos, punto en movimiento y
movimiento de cabeza), validación con vuelta del teclado, una comprobación de
deriva cinco minutos después con otra postura, y cuadros sueltos entre medio.

La mirada "en vivo" (``raw_x``, ``raw_y``) es el punto verdadero con ruido y
una deriva que crece con el tiempo, para que el banco de pruebas y el
reprocesamiento tengan algo que medir y corregir.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis import columns

T0 = 1_791_380_000_000.0
VIEWPORT = (1280.0, 720.0)
CSS_PX_PER_CM = 40.0
FRAME_MS = 33.0
DELAY_MS = 70.0
TRUTH = np.array([-2.2, 0.04, -2.8, -0.05, 0.6, 1, 1, 650, -90, 1.05, 0.97])
OPEN_REF = 0.3
CALIBRATION_POSE = {"yaw": 0.0, "pitch": -8.0, "distance": 58.0}
SHIFTED_POSE = {"yaw": 9.0, "pitch": -15.0, "distance": 66.0}
DRIFT_PX_PER_MIN = 12.0
"""Cuánto se corre la mirada en vivo por minuto (hacia la derecha y abajo)."""

_RAD = np.pi / 180


def iris_for(x: float, y: float, pose: dict[str, float]) -> tuple[float, float]:
    """Posición del iris (``h``, ``v``) que hace mirar un punto con una postura dada."""
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
class Simulation:
    """Sesión simulada.

    Attributes:
        frames: Filas de ``gaze_feature``.
        targets: Filas de ``gaze_target``.
        calibrations: Filas de ``calibration``.
        truth: Punto que miraba de verdad cada cuadro (``x``, ``y``), con el índice de ``frames``.
    """

    frames: pd.DataFrame
    targets: pd.DataFrame
    calibrations: pd.DataFrame
    truth: pd.DataFrame


class _Builder:
    """Acumula cuadros y objetivos en orden de tiempo."""

    def __init__(self, seed: int) -> None:
        self.random = np.random.default_rng(seed)
        self.t = T0
        self.frames: list[dict] = []
        self.truth: list[dict] = []
        self.targets: list[dict] = []

    def pose(
        self, center: dict[str, float], spread: tuple[float, float, float]
    ) -> dict[str, float]:
        """Postura al azar alrededor de una postura central."""
        jitter = lambda r: float(self.random.uniform(-r, r))  # noqa: E731
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
        look: tuple[float, float],
        pose: dict[str, float],
        *,
        state: str = "on_screen",
        blink: float = 0.02,
    ) -> None:
        """Agrega un cuadro que mira un punto, y avanza el reloj."""
        h, v = iris_for(look[0], look[1], pose)
        noise = lambda: float(self.random.normal(0, 0.0015))  # noqa: E731
        minutes = (self.t - T0) / 60_000
        drift = DRIFT_PX_PER_MIN * minutes
        self.frames.append(
            {
                "t": self.t,
                "face_detected": True,
                "head_yaw": pose["yaw"],
                "head_pitch": pose["pitch"],
                "head_roll": 0.0,
                "head_tx": 0.0,
                "head_ty": 0.0,
                "head_tz": -pose["distance"],
                "distance_cm": pose["distance"],
                "eye_u": pose["eye_u"],
                "eye_v": pose["eye_v"],
                "aspect": pose["aspect"],
                "left_h": h + noise(),
                "left_v": v + noise(),
                "left_open": pose["open"],
                "left_refined": True,
                "right_h": h + noise(),
                "right_v": v + noise(),
                "right_open": pose["open"],
                "right_refined": True,
                "blink": blink,
                "state": state,
                "confidence": 1.0,
                "raw_x": look[0] + drift + float(self.random.normal(0, 20)),
                "raw_y": look[1] + drift + float(self.random.normal(0, 20)),
                "viewport_width": VIEWPORT[0],
                "viewport_height": VIEWPORT[1],
                "scroll_x": 0.0,
                "scroll_y": 0.0,
            }
        )
        self.truth.append({"x": look[0], "y": look[1]})
        self.t += FRAME_MS

    def fixed(
        self,
        kind: str,
        phase: str,
        group: int,
        point: tuple[float, float],
        center: dict[str, float],
        spread: tuple[float, float, float],
        duration_ms: float,
    ) -> None:
        """Un objetivo fijo mirado durante un tramo."""
        start = self.t
        while self.t < start + duration_ms:
            self.frame(point, self.pose(center, spread))
        self.targets.append(
            self._target(kind, phase, group, start, [{"t": start, "x": point[0], "y": point[1]}])
        )
        self.t += 400  # Pausa entre objetivos: la mirada viaja al siguiente.

    def pursuit(self, duration_ms: float) -> None:
        """Punto en movimiento: cada cuadro muestra el ojo de ``DELAY_MS`` antes."""
        start = self.t
        width, height = VIEWPORT

        def position(t: float) -> tuple[float, float]:
            s = (t - start) / 1000
            return (
                width * (0.5 + 0.4 * np.sin(2 * np.pi * 0.15 * s)),
                height * (0.5 + 0.4 * np.sin(2 * np.pi * 0.2 * s)),
            )

        path = [
            {"t": t, "x": position(t)[0], "y": position(t)[1]}
            for t in np.arange(start, start + duration_ms, 16.0)
        ]
        while self.t < start + duration_ms:
            self.frame(position(self.t - DELAY_MS), self.pose(CALIBRATION_POSE, (2, 2, 2)))
        self.targets.append(self._target("initial", "pursuit", 0, start, path))
        self.t += 400

    def _target(self, kind: str, phase: str, group: int, start: float, points: list[dict]) -> dict:
        return {
            "t": start,
            "t_end": self.t,
            "calibration_type": kind,
            "phase": phase,
            "group": group,
            "viewport_width": VIEWPORT[0],
            "viewport_height": VIEWPORT[1],
            "points": points,
        }


def grid(fractions: tuple[float, ...]) -> list[tuple[float, float]]:
    """Puntos de una cuadrícula, en píxeles de la ventana."""
    return [(fx * VIEWPORT[0], fy * VIEWPORT[1]) for fy in fractions for fx in fractions]


def simulate(seed: int = 7) -> Simulation:
    """Arma la sesión simulada completa.

    Args:
        seed: Semilla del azar.

    Returns:
        Sesión simulada.
    """
    b = _Builder(seed)
    still = (2.0, 2.0, 2.0)
    for group, point in enumerate([*grid((0.1, 0.5, 0.9)), *grid((0.3, 0.7))]):
        b.fixed("initial", "points", group, point, CALIBRATION_POSE, still, 1100)
    b.pursuit(12_000)
    b.fixed("initial", "head", 0, (640, 360), CALIBRATION_POSE, (12, 10, 8), 8000)
    validation = [
        (0.2, 0.2),
        (0.8, 0.2),
        (0.2, 0.8),
        (0.8, 0.8),
        (0.5, 0.3),
        (0.5, 0.7),
        (0.3, 0.5),
        (0.7, 0.5),
    ]
    for group, (fx, fy) in enumerate(validation):
        b.fixed(
            "initial",
            "validation",
            group,
            (fx * VIEWPORT[0], fy * VIEWPORT[1]),
            CALIBRATION_POSE,
            still,
            1000,
        )
    # Mira el teclado (fuera de la pantalla) y vuelve al punto.
    for _ in range(40):
        b.frame(
            (640, 1300), b.pose({"yaw": 0, "pitch": -30, "distance": 58}, still), state="off_screen"
        )
    b.fixed("initial", "look_away", 0, (640, 324), CALIBRATION_POSE, still, 1000)
    calibration_end = b.t
    # Cinco minutos de uso con otra postura, y un parpadeo de vez en cuando.
    while b.t < T0 + 300_000:
        point = (float(b.random.uniform(100, 1180)), float(b.random.uniform(80, 640)))
        blink = 0.9 if b.random.random() < 0.05 else 0.02
        b.frame(
            point,
            b.pose(SHIFTED_POSE, still),
            blink=blink,
            state="blink" if blink > 0.5 else "on_screen",
        )
        b.t += 2 * FRAME_MS  # Menos cuadros fuera de los procedimientos, para que sea rápido.
    for group, point in enumerate([(640, 360), (256, 144), (1024, 576)]):
        b.fixed("drift_check", "drift_check", group, point, SHIFTED_POSE, still, 1100)
    frames = columns.frame("gaze_features", b.frames)
    calibrations = columns.frame(
        "gaze_calibrations",
        [
            {
                "t": calibration_end,
                "type": "initial",
                "error_px": 40.0,
                "error_deg": 1.0,
                "accepted": True,
                "camera_delay_ms": DELAY_MS,
                "estimator": "geometric",
            }
        ],
    )
    return Simulation(
        frames=frames,
        targets=columns.frame("gaze_targets", b.targets),
        calibrations=calibrations,
        truth=pd.DataFrame(b.truth, index=frames.index),
    )
