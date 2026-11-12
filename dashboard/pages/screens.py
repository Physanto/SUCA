"""Página Pantallas: dónde están los problemas del sistema evaluado, pantalla por pantalla."""

import pandas as pd
import streamlit as st
from PIL import Image

from dashboard import charts, heatmap, heatmap_insights, heatmap_view, replay, ui

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
    # Lo de cada sesión, para las gráficas que acompañan al mapa.
    all_events, all_fixations, all_attribution, all_states = [], [], [], []
    labels: dict[str, str] = {}
    for session_id in chosen["session_id"]:
        session = data.get_session(int(session_id))
        viewport = replay.viewport_of(session)
        events = data.get_events(int(session_id))
        located.append(heatmap.points(events, data.get_gaze(int(session_id)), layer or "click"))
        all_events.append(events)
        labels.update(heatmap_insights.labels_by_selector(events))
        if layer == "gaze":
            all_fixations.append(
                data.get_gaze_fixations(int(session_id)).assign(session_id=session_id)
            )
            all_attribution.append(
                data.get_gaze_attribution(int(session_id)).assign(session_id=session_id)
            )
            all_states.append(data.get_gaze_states(int(session_id)))

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


def _joined(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Une lo de varias sesiones; vacío si no hay ninguna."""
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


heatmap_view.show_details(
    layer or "click",
    screen,
    selected,
    viewport,
    events=_joined(all_events),
    fixations=_joined(all_fixations),
    attribution=_joined(all_attribution),
    states=_joined(all_states),
    labels=labels,
)

st.subheader("Resumen")
ui.show_table(screens)
