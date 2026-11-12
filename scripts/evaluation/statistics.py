"""Pruebas estadísticas del experimento: versiones, tendencia, correlación y acuerdo.

Usa scipy (dependencia opcional de ``requirements-ml.txt``). Cada función
devuelve números y una lectura breve; no decide umbrales de éxito, que se fijan
antes del experimento.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

VERSION_ORDER = ("V0", "V1", "V2")
"""Orden esperado de las versiones: de menos a más problemas."""


def _scipy() -> Any:
    """Importa ``scipy.stats`` o explica cómo instalarlo."""
    try:
        from scipy import stats
    except ImportError as error:
        raise RuntimeError("install requirements-ml.txt (scipy) to run the statistics") from error
    return stats


def describe_by_group(values: pd.DataFrame, column: str, group: str = "version") -> pd.DataFrame:
    """Estadística descriptiva de una columna por grupo.

    Args:
        values: Una fila por sesión.
        column: Columna numérica.
        group: Columna de los grupos.

    Returns:
        ``n``, ``mean``, ``sd``, ``median``, ``q1``, ``q3``, ``min`` y ``max`` por grupo.
    """
    rows = []
    for name, part in values.groupby(group, sort=True):
        data = part[column].dropna().astype(float)
        rows.append(
            {
                group: name,
                "n": len(data),
                "mean": data.mean() if len(data) else None,
                "sd": data.std(ddof=1) if len(data) > 1 else None,
                "median": data.median() if len(data) else None,
                "q1": data.quantile(0.25) if len(data) else None,
                "q3": data.quantile(0.75) if len(data) else None,
                "min": data.min() if len(data) else None,
                "max": data.max() if len(data) else None,
            }
        )
    return pd.DataFrame(rows)


def compare_groups(groups: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """Compara los grupos con ANOVA y Kruskal-Wallis, e informa la normalidad.

    Se informan ambas pruebas: la guía es ANOVA si todos los grupos parecen
    normales (Shapiro-Wilk, p > 0,05) y Kruskal-Wallis si no.

    Args:
        groups: Valores por grupo; cada uno con al menos 3 valores.

    Returns:
        ``shapiro`` (p por grupo), ``anova`` (F, p, eta²), ``kruskal`` (H, p,
        épsilon²) y ``suggested`` (``anova`` o ``kruskal``).

    Raises:
        ValueError: Con menos de dos grupos o algún grupo con menos de 3 valores.
    """
    stats = _scipy()
    data = {name: np.asarray(values, float) for name, values in groups.items()}
    if len(data) < 2 or any(len(values) < 3 for values in data.values()):
        raise ValueError("comparing versions needs at least two groups with 3 values each")
    shapiro = {
        name: float(stats.shapiro(values).pvalue) if np.ptp(values) > 0 else None
        for name, values in data.items()
    }
    samples = list(data.values())
    every = np.concatenate(samples)
    n, k = len(every), len(samples)
    anova = stats.f_oneway(*samples)
    between = sum(len(s) * (s.mean() - every.mean()) ** 2 for s in samples)
    total = ((every - every.mean()) ** 2).sum()
    kruskal = stats.kruskal(*samples)
    normal = all(p is not None and p > 0.05 for p in shapiro.values())
    return {
        "shapiro_p": shapiro,
        "anova": {
            "f": float(anova.statistic),
            "p": float(anova.pvalue),
            "eta_squared": float(between / total) if total > 0 else None,
        },
        "kruskal": {
            "h": float(kruskal.statistic),
            "p": float(kruskal.pvalue),
            "epsilon_squared": float((kruskal.statistic - k + 1) / (n - k)),
        },
        "suggested": "anova" if normal else "kruskal",
    }


def jonckheere_terpstra(
    groups: Sequence[Sequence[float]],
    *,
    alternative: str = "decreasing",
    permutations: int = 10_000,
    seed: int = 0,
) -> dict[str, float]:
    """Prueba de tendencia ordenada de Jonckheere-Terpstra.

    El estadístico cuenta, para cada par de grupos en orden, cuántos pares de
    valores siguen la tendencia (los empates cuentan 0,5). El valor p se
    obtiene por permutaciones de las etiquetas de grupo, exacto con empates.

    Args:
        groups: Valores de cada grupo, en el orden de la hipótesis (V0, V1, V2).
        alternative: ``decreasing`` (V0 > V1 > V2) o ``increasing``.
        permutations: Permutaciones para el valor p.
        seed: Semilla de las permutaciones.

    Returns:
        ``statistic``, ``expected`` (media bajo la hipótesis nula) y ``p`` (una cola).
    """
    if alternative not in ("decreasing", "increasing"):
        raise ValueError(f"alternative must be 'decreasing' or 'increasing', got {alternative}")
    samples = [np.asarray(values, float) for values in groups]
    if len(samples) < 2 or any(len(values) == 0 for values in samples):
        raise ValueError("the trend test needs at least two non-empty groups")
    sign = -1.0 if alternative == "decreasing" else 1.0
    sizes = [len(values) for values in samples]
    labels = np.repeat(np.arange(len(samples)), sizes)
    every = np.concatenate(samples) * sign

    def statistic(order: np.ndarray) -> float:
        total = 0.0
        for i in range(len(samples)):
            for j in range(i + 1, len(samples)):
                low, high = every[order == i], every[order == j]
                diff = high[None, :] - low[:, None]
                total += float((diff > 0).sum() + 0.5 * (diff == 0).sum())
        return total

    observed = statistic(labels)
    rng = np.random.default_rng(seed)
    count = sum(statistic(rng.permutation(labels)) >= observed for _ in range(permutations))
    pairs = sum(sizes[i] * sizes[j] for i in range(len(sizes)) for j in range(i + 1, len(sizes)))
    return {"statistic": observed, "expected": pairs / 2, "p": (count + 1) / (permutations + 1)}


def spearman(x: Sequence[float], y: Sequence[float]) -> dict[str, float | int | None]:
    """Correlación de Spearman con su valor p (dos colas).

    Args:
        x: Primera variable.
        y: Segunda variable; se descartan los pares con algún valor ausente.

    Returns:
        ``rho``, ``p`` y ``n``. Con menos de 3 pares, ``rho`` y ``p`` son nulos.
    """
    frame = pd.DataFrame({"x": x, "y": y}).dropna().astype(float)
    if len(frame) < 3 or frame["x"].nunique() < 2 or frame["y"].nunique() < 2:
        return {"rho": None, "p": None, "n": len(frame)}
    result = _scipy().spearmanr(frame["x"], frame["y"])
    return {"rho": float(result.statistic), "p": float(result.pvalue), "n": len(frame)}


def split_half(first: Sequence[float], second: Sequence[float]) -> dict[str, float | int | None]:
    """Consistencia entre dos mitades, con la corrección de Spearman-Brown.

    Args:
        first: Valor de cada sesión con la primera mitad.
        second: Valor con la segunda mitad, en el mismo orden.

    Returns:
        ``r`` (Pearson entre mitades), ``spearman_brown`` (``2r / (1 + r)``) y ``n``.
    """
    frame = pd.DataFrame({"a": first, "b": second}).dropna().astype(float)
    if len(frame) < 3 or frame["a"].std() == 0 or frame["b"].std() == 0:
        return {"r": None, "spearman_brown": None, "n": len(frame)}
    r = float(np.corrcoef(frame["a"], frame["b"])[0, 1])
    return {"r": r, "spearman_brown": 2 * r / (1 + r) if r > -1 else None, "n": len(frame)}


def discrepant_cases(
    values: pd.DataFrame, first: str, second: str, threshold: float = 0.5
) -> pd.DataFrame:
    """Sesiones en que dos medidas no coinciden (por ejemplo, IUC y SUS).

    Cada medida se pasa a rango percentil (0 a 1) dentro del estudio; una sesión
    es discrepante si sus rangos se separan en ``threshold`` o más.

    Args:
        values: Una fila por sesión.
        first: Primera medida.
        second: Segunda medida.
        threshold: Separación mínima de los rangos.

    Returns:
        Las sesiones discrepantes, con ``<medida>_rank`` y ``gap`` (primera
        menos segunda), de mayor a menor separación.
    """
    frame = values.dropna(subset=[first, second]).copy()
    if frame.empty:
        return frame.assign(gap=pd.Series(dtype=float))
    frame[f"{first}_rank"] = frame[first].rank(pct=True)
    frame[f"{second}_rank"] = frame[second].rank(pct=True)
    frame["gap"] = frame[f"{first}_rank"] - frame[f"{second}_rank"]
    chosen = frame[frame["gap"].abs() >= threshold]
    return chosen.reindex(chosen["gap"].abs().sort_values(ascending=False).index)


def cohen_kappa(first: Sequence[Any], second: Sequence[Any]) -> dict[str, float | int | None]:
    """Acuerdo entre dos codificaciones categóricas.

    Args:
        first: Categorías de una codificación (por ejemplo, la automática).
        second: Las de la otra, en el mismo orden.

    Returns:
        ``agreement`` (proporción de coincidencias), ``kappa`` y ``n``. Si el
        acuerdo esperado por azar es 1, ``kappa`` es nulo.
    """
    pairs = [
        (a, b) for a, b in zip(first, second, strict=True) if not _missing(a) and not _missing(b)
    ]
    if not pairs:
        return {"agreement": None, "kappa": None, "n": 0}
    left = pd.Series([a for a, _ in pairs], dtype=object)
    right = pd.Series([b for _, b in pairs], dtype=object)
    observed = float((left == right).mean())
    categories = set(left) | set(right)
    expected = sum(
        float((left == category).mean()) * float((right == category).mean())
        for category in categories
    )
    kappa = None if expected >= 1 else (observed - expected) / (1 - expected)
    return {"agreement": observed, "kappa": kappa, "n": len(pairs)}


def _missing(value: Any) -> bool:
    """Valor ausente (``None`` o NaN)."""
    return value is None or (isinstance(value, float) and np.isnan(value))
