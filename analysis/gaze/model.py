"""Estimador geométrico de mirada, el mismo que usa la extensión.

Repite las cuentas de ``extension/camera/gaze-geometry.js`` para volver a
ajustar la mirada después de la sesión con todos los objetivos conocidos. Por
cada cuadro:

1. El ojo gira dentro de la cabeza en proporción al desplazamiento del iris:
   ``θ = a_h·h + b_h`` y ``φ = a_v·v + b_v + c·(apertura − referencia)``.
2. La dirección suma el giro de la cabeza: ``yaw = g_y·yaw_cabeza + θ``,
   ``pitch = g_p·pitch_cabeza + φ``.
3. El rayo sale del punto medio entre los ojos (ubicado en 3D con su posición en
   la imagen y la distancia) y se corta con el plano de la pantalla.
4. El corte, en centímetros desde la cámara, se pasa a píxeles de la ventana con
   ``x = c_x + k_x·px_por_cm·P_x`` e ``y = c_y + k_y·px_por_cm·P_y``.

Los 11 parámetros se ajustan con Levenberg-Marquardt, con valores previos
razonables, y una ridge pequeña corrige el residuo si la validación cruzada
dejando fuera un objetivo a la vez dice que ayuda.

Solo usa numpy: las funciones son puras y se prueban sin la base.
"""

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

VERTICAL_FOV_DEG = 63.0
"""Campo de visión vertical que supone MediaPipe para su matriz de pose."""

PARAMS = ("a_h", "b_h", "a_v", "b_v", "c_open", "g_yaw", "g_pitch", "c_x", "c_y", "k_x", "k_y")
"""Nombres de los parámetros, en orden."""

FEATURE_COLUMNS = ("yaw", "pitch", "distance", "eye_u", "eye_v", "aspect", "h", "v", "open")
"""Columnas de las características geométricas de cada cuadro."""

SIGMA_PX = 50.0
"""Escala de los residuos en píxeles: pondera los datos frente a los valores previos."""

CAMERA_TO_VIEWPORT_CM = 2.5
"""Distancia típica de la cámara al borde superior de la ventana, en centímetros."""

RESIDUAL_LAMBDAS: tuple[float | None, ...] = (None, 10.0, 100.0, 1000.0)
"""Penalizaciones de la ridge del residuo; ``None`` es "sin residuo"."""

MIN_GROUPS = 4
"""Objetivos distintos que hacen falta para entrenar."""

_RAD = np.pi / 180


def priors(viewport_width: float, css_px_per_cm: float) -> tuple[np.ndarray, np.ndarray]:
    """Valores previos de los parámetros y cuánto pueden alejarse de ellos.

    El iris se mueve unos 0,4 anchos de ojo por radián de giro del ojo, así que
    ``a ≈ −2,5``: negativo porque la imagen no está espejada y porque en la
    imagen "abajo" es positivo.

    Args:
        viewport_width: Ancho de la ventana de la calibración, en píxeles CSS.
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.

    Returns:
        Media y desviación de cada parámetro, en el orden de ``PARAMS``.
    """
    mean = np.array(
        [
            -2.5,
            0,
            -2.5,
            0,
            0,
            1,
            1,
            viewport_width / 2,
            -CAMERA_TO_VIEWPORT_CM * css_px_per_cm,
            1,
            1,
        ],
        dtype=float,
    )
    sigma = np.array(
        [3, 1, 3, 1, 5, 0.5, 0.5, viewport_width, 20 * css_px_per_cm, 0.3, 0.3], dtype=float
    )
    return mean, sigma


def project(
    params: np.ndarray, features: pd.DataFrame, css_px_per_cm: float, open_ref: float
) -> tuple[np.ndarray, np.ndarray]:
    """Punto de la ventana que mira cada cuadro con unos parámetros.

    Args:
        params: Parámetros, en el orden de ``PARAMS``.
        features: Una fila por cuadro con las columnas de ``FEATURE_COLUMNS``
            (ángulos de la cabeza en grados, distancia en centímetros).
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.
        open_ref: Apertura de referencia de los ojos.

    Returns:
        Coordenadas ``x`` e ``y`` en píxeles CSS de la ventana.
    """
    p = params
    h = features["h"].to_numpy(float)
    v = features["v"].to_numpy(float)
    theta = p[0] * h + p[1]
    phi = p[2] * v + p[3] + p[4] * (features["open"].to_numpy(float) - open_ref)
    yaw = p[5] * features["yaw"].to_numpy(float) * _RAD + theta
    pitch = p[6] * features["pitch"].to_numpy(float) * _RAD + phi
    tan_v = np.tan(VERTICAL_FOV_DEG * _RAD / 2)
    tan_h = tan_v * features["aspect"].to_numpy(float)
    # Ejes de la pantalla vistos por la persona: x a su derecha e y hacia abajo.
    oz = features["distance"].to_numpy(float)
    ox = -(features["eye_u"].to_numpy(float) - 0.5) * 2 * tan_h * oz
    oy = (features["eye_v"].to_numpy(float) - 0.5) * 2 * tan_v * oz
    px = ox + oz * np.tan(yaw)
    py = oy - oz * np.tan(pitch) / np.cos(yaw)
    return p[7] + p[9] * css_px_per_cm * px, p[8] + p[10] * css_px_per_cm * py


def levenberg_marquardt(
    residuals: Callable[[np.ndarray], np.ndarray],
    initial: np.ndarray,
    *,
    iterations: int = 60,
    tolerance: float = 1e-9,
) -> np.ndarray:
    """Minimiza la suma de cuadrados de unos residuos (jacobiano por diferencias finitas).

    Args:
        residuals: Residuos para unos parámetros; siempre del mismo largo.
        initial: Parámetros iniciales.
        iterations: Máximo de iteraciones.
        tolerance: Mejora relativa mínima para seguir.

    Returns:
        Parámetros ajustados.
    """
    params = np.asarray(initial, dtype=float).copy()
    current = residuals(params)
    cost = float(current @ current)
    damping = 1e-3
    for _ in range(iterations):
        steps = 1e-6 * np.maximum(1.0, np.abs(params))
        jacobian = np.empty((current.size, params.size))
        for j in range(params.size):
            shifted = params.copy()
            shifted[j] += steps[j]
            jacobian[:, j] = (residuals(shifted) - current) / steps[j]
        jtj = jacobian.T @ jacobian
        jtr = jacobian.T @ current
        improved = False
        for _attempt in range(10):
            damped = jtj + damping * np.diag(np.where(np.diag(jtj) > 0, np.diag(jtj), 1.0))
            try:
                delta = -np.linalg.solve(damped, jtr)
            except np.linalg.LinAlgError:
                damping *= 10
                continue
            candidate = params + delta
            following = residuals(candidate)
            following_cost = float(following @ following)
            if np.isfinite(following_cost) and following_cost < cost:
                gain = (cost - following_cost) / max(cost, 1e-300)
                params, current, cost = candidate, following, following_cost
                damping = max(damping / 10, 1e-12)
                improved = True
                if gain < tolerance:
                    return params
                break
            damping *= 10
        if not improved:
            break
    return params


@dataclass(frozen=True)
class Residual:
    """Ridge que corrige lo que la geometría no explica.

    Attributes:
        mean: Media de cada característica del entrenamiento.
        std: Desviación de cada característica (1 si es constante).
        weights: Pesos, una fila por característica y una columna por eje.
        bias: Residuo medio de cada eje.
    """

    mean: np.ndarray
    std: np.ndarray
    weights: np.ndarray
    bias: np.ndarray

    def apply(self, rows: np.ndarray) -> np.ndarray:
        """Residuo estimado para unas filas de características."""
        return self.bias + ((rows - self.mean) / self.std) @ self.weights


def _residual_rows(features: pd.DataFrame, open_ref: float) -> np.ndarray:
    """Características del residuo: segundo orden del iris, apertura y pose."""
    h = features["h"].to_numpy(float)
    v = features["v"].to_numpy(float)
    return np.column_stack(
        [
            h,
            v,
            h * h,
            v * v,
            h * v,
            features["open"].to_numpy(float) - open_ref,
            features["yaw"].to_numpy(float),
            features["pitch"].to_numpy(float),
            features["distance"].to_numpy(float),
        ]
    )


def fit_residual(rows: np.ndarray, targets: np.ndarray, lam: float) -> Residual:
    """Entrena una ridge sobre características estandarizadas.

    Args:
        rows: Características, una fila por muestra.
        targets: Residuo ``[x, y]`` de cada muestra.
        lam: Penalización.

    Returns:
        Ridge entrenada.
    """
    mean = rows.mean(axis=0)
    std = rows.std(axis=0)
    std = np.where(std > 1e-9, std, 1.0)
    standard = (rows - mean) / std
    bias = targets.mean(axis=0)
    weights = np.linalg.solve(
        standard.T @ standard + lam * np.eye(rows.shape[1]), standard.T @ (targets - bias)
    )
    return Residual(mean=mean, std=std, weights=weights, bias=bias)


@dataclass(frozen=True)
class GeometricModel:
    """Estimador geométrico ajustado a una persona.

    Attributes:
        params: Parámetros, en el orden de ``PARAMS``.
        open_ref: Apertura de referencia de los ojos (mediana del entrenamiento).
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.
        residual: Corrección del residuo, o ``None``.
    """

    params: np.ndarray
    open_ref: float
    css_px_per_cm: float
    residual: Residual | None = None

    def predict(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Estima el punto mirado en cada cuadro.

        Args:
            features: Características geométricas (``FEATURE_COLUMNS``).

        Returns:
            Coordenadas ``x`` e ``y`` en píxeles CSS de la ventana.
        """
        x, y = project(self.params, features, self.css_px_per_cm, self.open_ref)
        if self.residual is not None:
            correction = self.residual.apply(_residual_rows(features, self.open_ref))
            x, y = x + correction[:, 0], y + correction[:, 1]
        return x, y

    def named_params(self) -> dict[str, float]:
        """Parámetros por nombre."""
        return {name: float(value) for name, value in zip(PARAMS, self.params, strict=True)}


@dataclass(frozen=True)
class FitResult:
    """Resultado de un ajuste.

    Attributes:
        model: Modelo ajustado, o ``None`` si faltaron objetivos.
        cv_error_px: Error medio en validación cruzada (cada objetivo pesa igual).
        lam: Penalización del residuo elegida; ``None`` sin residuo.
        groups: Objetivos distintos.
    """

    model: GeometricModel | None
    cv_error_px: float | None
    lam: float | None
    groups: int


def _fit_params(
    features: pd.DataFrame,
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    css_px_per_cm: float,
    open_ref: float,
    prior: tuple[np.ndarray, np.ndarray],
    initial: np.ndarray,
) -> np.ndarray:
    """Ajusta los parámetros; cada objetivo pesa lo mismo, tenga los cuadros que tenga."""
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    weights = np.sqrt(1.0 / (counts[inverse] * counts.size)) / SIGMA_PX
    mean, sigma = prior

    def residuals(p: np.ndarray) -> np.ndarray:
        px, py = project(p, features, css_px_per_cm, open_ref)
        return np.concatenate([weights * (px - x), weights * (py - y), (p - mean) / sigma])

    return levenberg_marquardt(residuals, initial)


def fit_geometric(
    features: pd.DataFrame,
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    groups: Sequence[Hashable] | np.ndarray,
    *,
    viewport_width: float,
    css_px_per_cm: float,
) -> FitResult:
    """Ajusta el estimador y elige el residuo por validación cruzada.

    Args:
        features: Características geométricas de cada muestra (``FEATURE_COLUMNS``).
        x: Coordenada horizontal mirada en cada muestra.
        y: Coordenada vertical mirada.
        groups: Objetivo de cada muestra; la validación cruzada deja fuera uno a la vez.
        viewport_width: Ancho de la ventana, para el valor previo de ``c_x``.
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.

    Returns:
        Modelo ajustado y su error en validación cruzada.
    """
    features = features.reset_index(drop=True)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    groups = np.asarray([str(group) for group in groups])
    unique = list(dict.fromkeys(groups))
    if len(unique) < MIN_GROUPS:
        return FitResult(model=None, cv_error_px=None, lam=None, groups=len(unique))
    prior = priors(viewport_width, css_px_per_cm)
    open_ref = float(np.median(features["open"].to_numpy(float)))
    params = _fit_params(features, x, y, groups, css_px_per_cm, open_ref, prior, prior[0])
    errors = np.zeros(len(RESIDUAL_LAMBDAS))
    for left in unique:
        train = groups != left
        test = ~train
        fold = _fit_params(
            features[train],
            x[train],
            y[train],
            groups[train],
            css_px_per_cm,
            open_ref,
            prior,
            params,
        )
        for k, lam in enumerate(RESIDUAL_LAMBDAS):
            model = _with_residual(
                fold, features[train], x[train], y[train], css_px_per_cm, open_ref, lam
            )
            px, py = model.predict(features[test])
            errors[k] += np.mean(np.hypot(px - x[test], py - y[test])) / len(unique)
    best = int(np.argmin(errors))
    lam = RESIDUAL_LAMBDAS[best]
    model = _with_residual(params, features, x, y, css_px_per_cm, open_ref, lam)
    return FitResult(model=model, cv_error_px=float(errors[best]), lam=lam, groups=len(unique))


def _with_residual(
    params: np.ndarray,
    features: pd.DataFrame,
    x: np.ndarray,
    y: np.ndarray,
    css_px_per_cm: float,
    open_ref: float,
    lam: float | None,
) -> GeometricModel:
    """Modelo con unos parámetros y, si ``lam`` no es ``None``, su residuo entrenado."""
    model = GeometricModel(params=params, open_ref=open_ref, css_px_per_cm=css_px_per_cm)
    if lam is None:
        return model
    px, py = model.predict(features)
    residual = fit_residual(
        _residual_rows(features, open_ref), np.column_stack([x - px, y - py]), lam
    )
    return GeometricModel(
        params=params, open_ref=open_ref, css_px_per_cm=css_px_per_cm, residual=residual
    )


def fit_with_lambda(
    features: pd.DataFrame,
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    groups: Sequence[Hashable] | np.ndarray,
    *,
    viewport_width: float,
    css_px_per_cm: float,
    lam: float | None,
    initial: np.ndarray | None = None,
) -> GeometricModel:
    """Ajusta el estimador con una penalización del residuo ya elegida, sin validación cruzada.

    Sirve para los ajustes repetidos de una validación dejando fuera un objetivo,
    después de elegir el residuo con ``fit_geometric``.

    Args:
        features: Características geométricas de cada muestra.
        x: Coordenada horizontal mirada.
        y: Coordenada vertical mirada.
        groups: Objetivo de cada muestra (para pesar cada objetivo por igual).
        viewport_width: Ancho de la ventana, para el valor previo de ``c_x``.
        css_px_per_cm: Píxeles CSS por centímetro de la pantalla.
        lam: Penalización del residuo; ``None`` sin residuo.
        initial: Parámetros iniciales; por omisión, los valores previos.

    Returns:
        Modelo ajustado.
    """
    features = features.reset_index(drop=True)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    groups = np.asarray([str(group) for group in groups])
    prior = priors(viewport_width, css_px_per_cm)
    open_ref = float(np.median(features["open"].to_numpy(float)))
    start = prior[0] if initial is None else initial
    params = _fit_params(features, x, y, groups, css_px_per_cm, open_ref, prior, start)
    return _with_residual(params, features, x, y, css_px_per_cm, open_ref, lam)
