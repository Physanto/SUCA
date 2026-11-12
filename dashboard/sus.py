"""Lectura del SUS: qué significa un puntaje y qué ítems lo bajaron.

El puntaje SUS (0 a 100) se calcula al guardar la respuesta (``server.services``).
Este módulo lo **interpreta** y lo **desglosa por ítem**, sin tocar la base:

- la **calificación** frente a las referencias de la literatura: el promedio
  histórico (68) y las bandas de adjetivos de Bangor, Kortum y Miller (2009),
  más la nota de A a F de la escala de Sauro y Lewis (2016);
- la **contribución** de cada ítem (0 a 4 puntos): qué aspecto del sistema
  (complejidad, consistencia, confianza…) restó más.

Con pocas respuestas el SUS es solo indicativo; ``reliability`` lo advierte.
Funciones puras sobre listas y DataFrames: no importa Streamlit.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

AVERAGE_SUS = 68.0
"""Puntaje promedio de miles de estudios (Sauro y Lewis): por debajo, peor que el promedio."""

MIN_RESPONSES = 5
"""Respuestas desde las que el SUS deja de ser solo una anécdota."""

SOLID_RESPONSES = 12
"""Respuestas desde las que el promedio es razonablemente estable."""

ITEMS: tuple[tuple[str, bool], ...] = (
    ("Usaría el sistema con frecuencia", True),
    ("Lo encontró innecesariamente complejo", False),
    ("Le pareció fácil de usar", True),
    ("Necesitaría ayuda técnica para usarlo", False),
    ("Las funciones están bien integradas", True),
    ("Había demasiada inconsistencia", False),
    ("La mayoría aprendería a usarlo rápido", True),
    ("Le pareció muy incómodo de usar", False),
    ("Se sintió seguro usándolo", True),
    ("Necesitó aprender muchas cosas antes de usarlo", False),
)
"""Resumen de cada ítem del SUS y si está redactado en positivo.

Son resúmenes para leer el desglose, no el texto validado que ve el participante
(ese está en el panel de la extensión).
"""

#: Notas de la escala de Sauro y Lewis: puntaje mínimo de cada una, de mayor a menor.
GRADES: tuple[tuple[float, str], ...] = (
    (84.1, "A+"),
    (80.8, "A"),
    (78.9, "A-"),
    (77.2, "B+"),
    (74.1, "B"),
    (72.6, "B-"),
    (71.1, "C+"),
    (65.0, "C"),
    (62.7, "C-"),
    (51.7, "D"),
    (0.0, "F"),
)

#: Bandas de adjetivos de Bangor et al.: puntaje mínimo, etiqueta y tono (good, ok, bad).
BANDS: tuple[tuple[float, str, str], ...] = (
    (85.5, "Excelente", "good"),
    (71.4, "Bueno", "good"),
    (50.9, "Aceptable", "ok"),
    (0.0, "Pobre", "bad"),
)


@dataclass(frozen=True)
class Rating:
    """Lectura de un puntaje SUS.

    Attributes:
        score: Puntaje de 0 a 100.
        label: Adjetivo (``Excelente``, ``Bueno``, ``Aceptable`` o ``Pobre``).
        grade: Nota de A+ a F.
        tone: ``good``, ``ok`` o ``bad``, para el color.
        versus_average: Frase que lo compara con el promedio de 68.
    """

    score: float
    label: str
    grade: str
    tone: str
    versus_average: str


def rate(score: float) -> Rating:
    """Interpreta un puntaje SUS.

    Args:
        score: Puntaje de 0 a 100.

    Returns:
        La calificación, con su nota y su comparación con el promedio.

    Raises:
        ValueError: Si el puntaje no está entre 0 y 100.
    """
    if not 0 <= score <= 100:
        raise ValueError(f"the SUS score must be between 0 and 100, got {score}")
    _, label, tone = next(band for band in BANDS if score >= band[0])
    grade = next(name for minimum, name in GRADES if score >= minimum)
    gap = score - AVERAGE_SUS
    if abs(gap) < 1:
        versus = "Igual al promedio (68)."
    elif gap > 0:
        versus = f"{gap:.0f} puntos por encima del promedio (68)."
    else:
        versus = f"{-gap:.0f} puntos por debajo del promedio (68)."
    return Rating(float(score), label, grade, tone, versus)


def reliability(responses: int) -> str:
    """Cuánto confiar en un SUS promedio según cuántas respuestas lo forman.

    Args:
        responses: Cantidad de respuestas.

    Returns:
        Una advertencia en español; vacía si ya hay respuestas suficientes.
    """
    if responses == 0:
        return "Nadie respondió el SUS."
    if responses < MIN_RESPONSES:
        return (
            f"Solo {responses} respuesta(s): el SUS es una anécdota, no una medida. "
            f"Se vuelve indicativo desde {MIN_RESPONSES} y razonablemente estable desde "
            f"{SOLID_RESPONSES}."
        )
    if responses < SOLID_RESPONSES:
        return (
            f"{responses} respuestas: es indicativo, con bastante incertidumbre. "
            f"Desde {SOLID_RESPONSES} es más estable."
        )
    return ""


def contributions(answers: Sequence[int]) -> list[int]:
    """Puntos (0 a 4) que aporta cada ítem al puntaje, con la fórmula estándar.

    Args:
        answers: Las 10 respuestas, de 1 a 5, en orden.

    Returns:
        Aporte de cada ítem: ``respuesta - 1`` en los positivos y ``5 - respuesta``
        en los negativos. La suma por 2,5 es el puntaje SUS.

    Raises:
        ValueError: Si no son 10 respuestas de 1 a 5.
    """
    if len(answers) != len(ITEMS) or any(not 1 <= answer <= 5 for answer in answers):
        raise ValueError("the SUS needs 10 answers from 1 to 5")
    return [
        answer - 1 if positive else 5 - answer
        for answer, (_, positive) in zip(answers, ITEMS, strict=True)
    ]


def item_breakdown(answers: pd.DataFrame) -> pd.DataFrame:
    """Aporte medio de cada ítem sobre todas las respuestas.

    Args:
        answers: Una fila por respuesta con ``answers`` (lista de 10 enteros), como
            ``DashboardData.get_sus_answers``.

    Returns:
        Una fila por ítem, del que más resta al que menos: ``item`` (posición
        desde 1), ``text``, ``positive``, ``mean`` (0 a 4) y ``share_low`` (fracción
        de respuestas en que aportó 2 o menos). Vacía si no hay respuestas válidas.
    """
    columns = ["item", "text", "positive", "mean", "share_low"]
    rows = []
    for value in answers["answers"] if "answers" in answers else []:
        try:
            rows.append(contributions(list(value)))
        except (TypeError, ValueError):
            continue
    if not rows:
        return pd.DataFrame(columns=columns)
    table = np.asarray(rows, float)
    result = pd.DataFrame(
        {
            "item": range(1, len(ITEMS) + 1),
            "text": [text for text, _ in ITEMS],
            "positive": [positive for _, positive in ITEMS],
            "mean": table.mean(axis=0),
            "share_low": (table <= 2).mean(axis=0),
        }
    )
    return result.sort_values(["mean", "item"], ignore_index=True)


def summarize(scores: Sequence[Any]) -> dict[str, Any]:
    """Resumen de los puntajes SUS de un grupo.

    Args:
        scores: Puntajes; se ignoran los vacíos.

    Returns:
        ``count``, ``mean``, ``median``, ``min``, ``max`` (nulos sin respuestas),
        ``rating`` (``Rating`` del promedio o ``None``) y ``warning``.
    """
    values = pd.to_numeric(pd.Series(list(scores)), errors="coerce").dropna()
    if values.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "rating": None,
            "warning": reliability(0),
        }
    mean = float(values.mean())
    return {
        "count": len(values),
        "mean": mean,
        "median": float(values.median()),
        "min": float(values.min()),
        "max": float(values.max()),
        "rating": rate(min(100.0, max(0.0, mean))),
        "warning": reliability(len(values)),
    }
