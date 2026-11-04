"""Página Pantallas: dónde están los problemas del sistema evaluado, pantalla por pantalla."""

import pandas as pd
import streamlit as st
from PIL import Image

from dashboard import charts, heatmap, replay, ui

ui.page_header(
    "Pantallas",
    "Incidentes y tiempo en cada pantalla del estudio, y mapas de calor de clics, cursor y mirada "
    "de todas las sesiones juntas, por versión.",
)

with ui.selected_data() as data:
    study_id = ui.selected_study(data)
    screens = data.get_screen_summary(study_id)
    incidents = data.get_incidents(study_id=study_id)
    sessions = data.get_sessions(study_id=study_id, modes=["guided", "free"])
    captures = data.get_screen_captures(study_id)
    versions = st.multiselect(
        "Versiones", sorted(sessions["version"].unique()), key="screens_versions",
        help="Sin elegir ninguna, se juntan todas.",
    )  # fmt: skip
    chosen = sessions[sessions["version"].isin(versions)] if versions else sessions
    layer = st.segmented_control(
        "Capa del mapa", list(heatmap.LAYERS), format_func=heatmap.LAYERS.get, default="click",
        key="screens_layer",
    )  # fmt: skip
    located = []
    viewport = heatmap.DEFAULT_VIEWPORT
    for session_id in chosen["session_id"]:
        session = data.get_session(int(session_id))
        viewport = replay.viewport_of(session)
        located.append(
            heatmap.points(
                data.get_events(int(session_id)), data.get_gaze(int(session_id)), layer or "click"
            )
        )

if screens.empty:
    st.caption("Todavía no hay pantallas: analiza las sesiones.")
    st.stop()

left, right = st.columns(2)
with left:
    st.caption("Incidentes por pantalla")
    if incidents.empty:
        st.caption("Sin incidentes.")
    else:
        st.altair_chart(charts.incidents_by_screen(incidents), width="stretch")
with right:
    st.caption("Tiempo en cada pantalla")
    st.altair_chart(charts.time_by_screen(screens), width="stretch")

st.subheader("Mapa de calor del estudio")
all_points = (
    pd.concat(located, ignore_index=True)
    if located
    else pd.DataFrame(columns=["t", "screen", "x", "y"])
)
options = screens["screen"].tolist()
screen = st.selectbox("Pantalla", options, key="screens_screen")
shots = captures[[heatmap.screen_key(url) == screen for url in captures["url"]]]
background = Image.open(shots.iloc[-1]["absolute_path"]) if not shots.empty else None
selected = all_points[all_points["screen"] == screen][["x", "y"]].to_numpy()
drawn = heatmap.render(selected, layer=layer or "click", background=background, viewport=viewport)
st.image(drawn.image, width="stretch")
st.caption(
    f"{len(chosen)} sesiones · {drawn.drawn} puntos dibujados"
    + (f"; {drawn.outside} fuera de la imagen" if drawn.outside else "")
    + ("." if background is not None else ". Sin captura de esta pantalla: fondo neutro.")
)

st.subheader("Resumen")
ui.show_table(screens)
