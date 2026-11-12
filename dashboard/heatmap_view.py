"""Lo que acompaña a un mapa de calor en las páginas: explicación y gráficas por capa.

Lo usan la página Sesión (una sesión) y la página Pantallas (todas las sesiones
de un estudio juntas). Los cálculos están en ``dashboard.heatmap_insights`` y
las gráficas en ``dashboard.charts``; aquí solo se disponen con Streamlit.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd
import streamlit as st

from dashboard import charts, heatmap, heatmap_insights


def show_details(
    layer: str,
    screen: str,
    xy: np.ndarray,
    viewport: tuple[int, int],
    *,
    events: pd.DataFrame,
    fixations: pd.DataFrame,
    attribution: pd.DataFrame,
    states: pd.DataFrame,
    labels: Mapping[str, str],
) -> None:
    """Muestra qué representa el mapa de calor de una capa y sus números.

    Args:
        layer: ``click``, ``cursor`` o ``gaze``.
        screen: Pantalla normalizada que muestra el mapa.
        xy: Posiciones dibujadas en el mapa, en coordenadas de la página.
        viewport: Ancho y alto de la ventana, en píxeles CSS.
        events: Eventos de las sesiones del mapa.
        fixations: Fijaciones atribuidas (``gaze_fixation``) de esas sesiones.
        attribution: Candidatos de cada fijación (``gaze_attribution``).
        states: Estado de cada muestra de mirada (``t``, ``state``).
        labels: Nombre legible de cada selector.
    """
    what = {"click": "clics", "cursor": "muestras del cursor", "gaze": "muestras de mirada"}[layer]
    with st.expander("¿Qué representa este mapa?", expanded=True):
        st.markdown(heatmap_insights.EXPLANATIONS[layer])
    if len(xy) == 0:
        st.caption(f"Sin {what} en esta pantalla.")
        return
    left, right = st.columns(2)
    with left:
        st.caption(
            f"Dónde se concentran los {what}: la primera vista de la pantalla en 3 × 3 y, "
            "abajo, lo que quedó debajo (se llega con scroll)."
        )
        st.altair_chart(
            charts.zone_grid(heatmap_insights.zone_shares(xy, viewport), what), width="stretch"
        )
    with right:
        if layer == "click":
            _clicks(events, screen)
        elif layer == "cursor":
            _cursor(events, screen, len(xy))
        else:
            _gaze(fixations, attribution, states, screen, labels)


def _clicks(events: pd.DataFrame, screen: str) -> None:
    """Elementos más clicados y clics en lo que no responde."""
    top = heatmap_insights.top_clicked(events, screen)
    if top.empty:
        st.caption("Sin clics sobre elementos en esta pantalla.")
        return
    total = int(top["clicks"].sum())
    dead = int(top.loc[~top["interactive"].astype(bool), "clicks"].sum())
    st.caption(
        "Elementos con más clics. En naranja, los que no son enlaces, botones ni campos: "
        "si reciben clics, la gente esperaba que respondieran."
    )
    st.altair_chart(charts.top_elements(top, "clicks", "Clics"), width="stretch")
    st.metric(
        "Clics en elementos no interactivos",
        f"{dead / total:.0%}" if total else "—",
        help="Entre los elementos que aparecen en la gráfica.",
    )


def _cursor(events: pd.DataFrame, screen: str, samples: int) -> None:
    """Recorrido del cursor."""
    distance = heatmap_insights.cursor_distance_px(events, screen)
    st.metric(
        "Recorrido del cursor",
        f"{distance / 1000:.1f} mil px",
        help="Suma de lo que se movió el cursor en esta pantalla, en píxeles CSS.",
    )
    st.metric("Muestras del cursor", f"{samples}")
    st.caption(
        "Un recorrido largo con pocos clics suele indicar búsqueda: la persona recorre la "
        "pantalla sin encontrar dónde ir."
    )


def _gaze(
    fixations: pd.DataFrame,
    attribution: pd.DataFrame,
    states: pd.DataFrame,
    screen: str,
    labels: Mapping[str, str],
) -> None:
    """Tiempo de mirada por elemento, sin asignar y estados de la mirada."""
    dwell = heatmap_insights.gaze_dwell(fixations, attribution, screen, labels)
    if dwell.empty:
        st.caption(
            "Sin atribución de la mirada a elementos en esta pantalla: analiza la sesión "
            "(python -m analysis.run) para calcularla."
        )
    else:
        st.caption(
            "Tiempo de mirada estimado sobre cada elemento. Cada fijación reparte su duración "
            "según la probabilidad de cada elemento (solo con la mirada, sin usar los clics). "
            "En gris, el tiempo sin asignar: mirando el vacío, distraída o pensando."
        )
        st.altair_chart(
            charts.top_elements(dwell, "seconds", "Segundos", fmt=".1f"), width="stretch"
        )
        here = fixations[[heatmap.screen_key(url or "") == screen for url in fixations["screen"]]]
        if len(here):
            ambiguous = here["ambiguous"].fillna(False).astype(bool).mean()
            stares = int(here["long_stare"].fillna(False).astype(bool).sum())
            st.caption(
                f"{len(here)} fijaciones · {ambiguous:.0%} ambiguas (se resolvieron al contenedor "
                f"que reúne a los candidatos) · {stares} miradas fijas prolongadas sin actividad."
            )
    shares = heatmap_insights.gaze_state_shares(states)
    if not shares.empty:
        st.caption(
            "Estados de la mirada en toda la sesión. El mapa solo dibuja cuando mira la "
            "pantalla; el resto es tiempo mirando fuera (teclado, habitación), parpadeando o "
            "antes de calibrar."
        )
        st.altair_chart(charts.gaze_states(shares), width="stretch")
