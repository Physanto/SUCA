"""Relación orientativa entre los incidentes y las 10 heurísticas de Nielsen.

**No es una evaluación heurística.** Esa la hace un experto inspeccionando la
interfaz. Aquí se toma cada tipo de incidente que detecta el análisis y se
indica a qué heurística suele apuntar, para que el evaluador sepa dónde mirar:

- un incidente es un *indicio* de la heurística, no una violación probada;
- las heurísticas sin indicios no están «cumplidas»: varias no se pueden
  observar en el comportamiento (estética, ayuda y documentación).

La relación es una decisión editorial del proyecto, con su razón en ``LINKS``.
Funciones puras sobre DataFrames: no importa Streamlit.
"""

from collections.abc import Mapping

import pandas as pd

HEURISTICS: Mapping[int, str] = {
    1: "Visibilidad del estado del sistema",
    2: "Correspondencia entre el sistema y el mundo real",
    3: "Control y libertad del usuario",
    4: "Consistencia y estándares",
    5: "Prevención de errores",
    6: "Reconocer antes que recordar",
    7: "Flexibilidad y eficiencia de uso",
    8: "Diseño estético y minimalista",
    9: "Ayudar a reconocer, diagnosticar y recuperarse de errores",
    10: "Ayuda y documentación",
}
"""Las 10 heurísticas de usabilidad de Nielsen, en español."""

LINKS: Mapping[str, tuple[tuple[int, ...], str]] = {
    "rage_click": (
        (1,),
        "Varios clics seguidos suelen indicar que no hubo una respuesta visible.",
    ),
    "dead_click": (
        (1, 4),
        "Algo parece clicable y no responde: sin respuesta visible, y contra lo que se espera "
        "de un elemento con ese aspecto.",
    ),
    "navigation_loop": (
        (2, 6),
        "Ir y volver entre pantallas apunta a nombres poco claros o a no recordar dónde estaba "
        "la opción.",
    ),
    "long_pause": (
        (2, 6),
        "Una pausa larga suele ser duda: no entender lo que se ve o no saber qué hacer después.",
    ),
    "hesitation": (
        (2, 4),
        "Cursor detenido sobre un elemento: duda sobre qué hará o si es lo que se busca.",
    ),
    "form_error": (
        (5, 9),
        "Un error de validación muestra que el formulario no previno el error o no explicó "
        "cómo corregirlo.",
    ),
    "field_reentry": (
        (5, 9),
        "Volver a corregir un campo indica que el error no se previno o no se entendió.",
    ),
    "silent_failure": (
        (9, 1),
        "Envío que falla sin un aviso reconocible: el sitio no explica el error ni informa "
        "el estado.",
    ),
    "form_abandonment": (
        (5, 7),
        "Salir del formulario sin enviarlo apunta a errores que bloquean o a un proceso "
        "demasiado largo.",
    ),
    "repeated_search": (
        (2, 7),
        "Reformular la búsqueda apunta a un buscador que no entiende el lenguaje de la persona.",
    ),
    "task_overtime": (
        (7,),
        "Una tarea mucho más larga que la ruta ideal apunta a un camino poco eficiente.",
    ),
}
"""Por tipo de incidente: heurísticas a las que suele apuntar y por qué."""

NOT_OBSERVABLE: tuple[int, ...] = (8, 10)
"""Heurísticas que casi no dejan rastro en el comportamiento."""

CAVEAT = (
    "Relación orientativa por indicios, no una evaluación heurística: un incidente apunta a "
    "dónde mirar, no prueba que la heurística se incumpla. Las heurísticas sin indicios no "
    "están «cumplidas»: la estética (8) y la ayuda y documentación (10) casi no se ven en el "
    "comportamiento, y una inspección con una persona experta sigue siendo necesaria."
)
"""Aviso que acompaña a la tabla en el informe."""


def heuristic_table(incidents: pd.DataFrame, labels: Mapping[str, str]) -> pd.DataFrame:
    """Indicios que hay de cada heurística en un conjunto de incidentes.

    Args:
        incidents: Incidentes con ``session_id`` y ``type``.
        labels: Etiqueta en español de cada tipo de incidente.

    Returns:
        Una fila por heurística, en orden: ``number``, ``heuristic``, ``signs``
        (incidentes que apuntan a ella), ``sessions`` (sesiones con alguno),
        ``from_types`` (tipos y cuántos, de más a menos), ``observable`` (si el
        comportamiento puede mostrarla).
    """
    rows = []
    for number, name in HEURISTICS.items():
        types = [kind for kind, (numbers, _) in LINKS.items() if number in numbers]
        own = incidents[incidents["type"].isin(types)] if len(incidents) else incidents
        counts = own["type"].value_counts() if len(own) else pd.Series(dtype=int)
        rows.append(
            {
                "number": number,
                "heuristic": name,
                "signs": int(len(own)),
                "sessions": int(own["session_id"].nunique()) if len(own) else 0,
                "from_types": ", ".join(
                    f"{labels.get(kind, kind)} ({int(count)})" for kind, count in counts.items()
                ),
                "observable": number not in NOT_OBSERVABLE,
            }
        )
    return pd.DataFrame(rows)
