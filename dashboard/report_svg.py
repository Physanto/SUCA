"""Gráficas en SVG para el informe: barras, escala del SUS y línea de tiempo.

El informe es un único archivo HTML que debe verse sin internet y al imprimirlo,
así que las gráficas se dibujan aquí como SVG en vez de usar una librería con
JavaScript. Los colores salen de clases CSS (``good``, ``ok``, ``bad``,
``accent``, ``muted``) que define la hoja de estilo del informe, y cada gráfica
lleva su título y descripción para lectores de pantalla.

Funciones puras: reciben números y devuelven texto SVG.
"""

import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

BAR_HEIGHT = 22
"""Alto de cada barra, en píxeles."""

LABEL_WIDTH = 230
"""Ancho reservado a la etiqueta de cada barra."""

TYPE_CLASSES = 8
"""Colores distintos de los tipos de incidente en la línea de tiempo (clases ``t0`` a ``t7``)."""


@dataclass(frozen=True)
class Bar:
    """Una barra horizontal.

    Attributes:
        label: Texto a la izquierda.
        value: Valor; ``None`` si no hay dato (se dibuja vacía, con un guion).
        text: Texto a la derecha de la barra; por defecto, el valor.
        tone: Clase de color (``good``, ``ok``, ``bad``, ``accent`` o ``muted``).
    """

    label: str
    value: float | None
    text: str = ""
    tone: str = "accent"


def _tag(name: str, content: str = "", **attrs: object) -> str:
    """Un elemento SVG con sus atributos escapados.

    ``class_`` se escribe ``class`` y los guiones bajos pasan a guiones
    (``text_anchor`` → ``text-anchor``). Sin contenido, el elemento se cierra solo.
    """
    rendered = "".join(
        f' {key.rstrip("_").replace("_", "-")}="{escape(str(value))}"'
        for key, value in attrs.items()
    )
    return f"<{name}{rendered}>{content}</{name}>" if content else f"<{name}{rendered}/>"


def _short(text: str, limit: int) -> str:
    """Recorta un texto largo con puntos suspensivos."""
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _svg(width: int, height: int, title: str, description: str, body: Sequence[str]) -> str:
    """Contenedor ``<svg>`` accesible, con título y descripción."""
    uid = zlib.crc32(f"{title}|{description}".encode())
    inner = (
        _tag("title", escape(title), id=f"t{uid}")
        + _tag("desc", escape(description), id=f"d{uid}")
        + "".join(body)
    )
    return _tag(
        "svg",
        inner,
        class_="chart",
        role="img",
        viewBox=f"0 0 {width} {height}",
        aria_labelledby=f"t{uid} d{uid}",
    )


def bar_chart(
    bars: Sequence[Bar],
    *,
    maximum: float,
    title: str,
    description: str,
    width: int = 720,
    label_width: int = LABEL_WIDTH,
    reference: tuple[float, str] | None = None,
) -> str:
    """Barras horizontales con su etiqueta y su valor.

    Args:
        bars: Barras, de arriba abajo.
        maximum: Valor al que llega una barra completa.
        title: Título para lectores de pantalla.
        description: Qué muestra la gráfica, para lectores de pantalla.
        width: Ancho total del dibujo.
        label_width: Ancho reservado a las etiquetas; las más largas se recortan.
        reference: Línea vertical de referencia (valor y etiqueta), o ``None``.

    Returns:
        Un elemento ``<svg>``. Sin barras, un texto indicándolo.
    """
    if not bars:
        return '<p class="muted">Sin datos.</p>'
    track = width - label_width - 90
    limit = label_width // 6
    height = len(bars) * (BAR_HEIGHT + 8) + (22 if reference else 6)
    body = []
    for index, bar in enumerate(bars):
        y = index * (BAR_HEIGHT + 8) + 4
        body.append(_tag("text", escape(_short(bar.label, limit)), class_="label", x=0, y=y + 15))
        body.append(
            _tag("rect", class_="track", x=label_width, y=y, width=track, height=BAR_HEIGHT, rx=3)
        )
        if bar.value is not None and maximum > 0:
            fill = max(0.0, min(1.0, bar.value / maximum)) * track
            body.append(
                _tag(
                    "rect",
                    class_=f"bar {bar.tone}",
                    x=label_width,
                    y=y,
                    width=f"{fill:.1f}",
                    height=BAR_HEIGHT,
                    rx=3,
                )
            )
        shown = bar.text or ("—" if bar.value is None else f"{bar.value:g}")
        body.append(
            _tag("text", escape(shown), class_="value", x=label_width + track + 8, y=y + 15)
        )
    if reference is not None and maximum > 0:
        x = label_width + max(0.0, min(1.0, reference[0] / maximum)) * track
        body.append(_tag("line", class_="ref", x1=f"{x:.1f}", y1=0, x2=f"{x:.1f}", y2=height - 18))
        body.append(
            _tag(
                "text",
                escape(reference[1]),
                class_="ref-label",
                x=f"{x:.1f}",
                y=height - 4,
                text_anchor="middle",
            )
        )
    return _svg(width, height, title, description, body)


def sus_scale(scores: Sequence[tuple[str, float]], *, width: int = 720) -> str:
    """Escala del SUS con las bandas de calificación y el puntaje de cada persona.

    Args:
        scores: ``(etiqueta, puntaje)`` de cada respuesta, de 0 a 100.
        width: Ancho total del dibujo.

    Returns:
        Un ``<svg>`` con las bandas Pobre, Aceptable, Bueno y Excelente, la línea
        del promedio (68) y un punto por respuesta.
    """
    left, top = 10, 26
    track = width - 2 * left
    bands = (
        (0, 50.9, "bad", "Pobre"),
        (50.9, 71.4, "ok", "Aceptable"),
        (71.4, 85.5, "good", "Bueno"),
        (85.5, 100, "good2", "Excelente"),
    )

    def x_of(score: float) -> float:
        return left + max(0.0, min(100.0, score)) / 100 * track

    height = top + 30 + max(1, len(scores)) * 18
    body = []
    for low, high, tone, name in bands:
        body.append(
            _tag(
                "rect",
                class_=f"band {tone}",
                x=f"{x_of(low):.1f}",
                y=top,
                width=f"{x_of(high) - x_of(low):.1f}",
                height=22,
            )
        )
        body.append(
            _tag(
                "text",
                name,
                class_="band-label",
                x=f"{(x_of(low) + x_of(high)) / 2:.1f}",
                y=top + 15,
                text_anchor="middle",
            )
        )
    for tick in (0, 25, 50, 75, 100):
        body.append(
            _tag(
                "text",
                str(tick),
                class_="tick",
                x=f"{x_of(tick):.1f}",
                y=top - 8,
                text_anchor="middle",
            )
        )
    average = f"{x_of(68):.1f}"
    body.append(_tag("line", class_="ref", x1=average, y1=top - 4, x2=average, y2=height - 14))
    body.append(
        _tag(
            "text",
            "promedio 68",
            class_="ref-label",
            x=average,
            y=height - 2,
            text_anchor="middle",
        )
    )
    for index, (label, score) in enumerate(scores):
        y = top + 34 + index * 18
        body.append(_tag("circle", class_="dot", cx=f"{x_of(score):.1f}", cy=y, r=5))
        # Cerca del borde derecho la etiqueta va a la izquierda del punto, para que no se corte.
        near_edge = score > 70
        body.append(
            _tag(
                "text",
                escape(f"{_short(label, 28)} · {score:.0f}"),
                class_="dot-label",
                x=f"{x_of(score) + (-9 if near_edge else 9):.1f}",
                y=y + 4,
                text_anchor="end" if near_edge else "start",
            )
        )
    return _svg(
        width,
        height,
        "Puntaje SUS de cada respuesta sobre la escala de calificación",
        "Escala de 0 a 100 dividida en Pobre, Aceptable, Bueno y Excelente, con el promedio "
        "histórico de 68 marcado y un punto por cada respuesta.",
        body,
    )


@dataclass(frozen=True)
class TimelineRow:
    """Una sesión en la línea de tiempo.

    Attributes:
        label: Nombre de la fila (participante y versión).
        duration_ms: Duración de la sesión.
        tasks: ``(inicio, fin, texto)`` de cada tarea, en ms desde el inicio.
        marks: ``(momento, índice del tipo)`` de cada incidente, en ms desde el inicio.
    """

    label: str
    duration_ms: float
    tasks: Sequence[tuple[float, float, str]]
    marks: Sequence[tuple[float, int]]


def timeline(rows: Sequence[TimelineRow], legend: Sequence[str], *, width: int = 820) -> str:
    """Línea de tiempo de varias sesiones con sus tareas y sus incidentes.

    Args:
        rows: Una fila por sesión.
        legend: Nombre de cada tipo de incidente, en el orden de sus índices.
        width: Ancho total del dibujo.

    Returns:
        Un ``<svg>``. Cada sesión se dibuja a su propia escala de tiempo: las
        tareas son franjas y cada incidente, un punto del color de su tipo.
    """
    if not rows:
        return '<p class="muted">Sin sesiones.</p>'
    left, row_height = 150, 34
    track = width - left - 10
    height = len(rows) * row_height + 28 + 18 * ((len(legend) + 3) // 4)
    body = []
    for index, row in enumerate(rows):
        y = index * row_height + 6
        scale = track / max(row.duration_ms, 1.0)
        body.append(_tag("text", escape(_short(row.label, 22)), class_="label", x=0, y=y + 18))
        body.append(_tag("rect", class_="track", x=left, y=y + 4, width=track, height=20, rx=3))
        for number, (start, end, text) in enumerate(row.tasks):
            x, w = left + start * scale, max(2.0, (end - start) * scale)
            body.append(
                _tag(
                    "rect",
                    _tag("title", escape(text)),
                    class_=f"task{number % 2}",
                    x=f"{x:.1f}",
                    y=y + 4,
                    width=f"{w:.1f}",
                    height=20,
                )
            )
            body.append(
                _tag(
                    "text",
                    escape(_short(text, 6)),
                    class_="task-label",
                    x=f"{x + 3:.1f}",
                    y=y + 18,
                )
            )
        for moment, kind in row.marks:
            body.append(
                _tag(
                    "circle",
                    class_=f"mark t{kind % TYPE_CLASSES}",
                    cx=f"{left + moment * scale:.1f}",
                    cy=y + 14,
                    r=4.5,
                )
            )
    base = len(rows) * row_height + 16
    for index, name in enumerate(legend):
        x = (index % 4) * (width // 4)
        y = base + (index // 4) * 18
        body.append(_tag("circle", class_=f"mark t{index % TYPE_CLASSES}", cx=x + 6, cy=y, r=5))
        body.append(_tag("text", escape(_short(name, 24)), class_="legend", x=x + 16, y=y + 4))
    return _svg(
        width,
        height,
        "Línea de tiempo de las sesiones",
        "Una fila por sesión: franjas grises para las tareas y puntos de color para los "
        "incidentes, según su tipo.",
        body,
    )
