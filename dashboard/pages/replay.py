"""Página Reproducción: la sesión otra vez, dibujada sobre las pantallas, y la prueba de la mirada.

No vuelve a ejecutar la prueba en el sitio: dibuja lo capturado (cursor, clics,
scroll y mirada) sobre la captura de cada pantalla, en el tiempo en que pasó.
"""

import math

import pandas as pd
import streamlit as st

from dashboard import replay, ui
from shared.config import load_config

ui.page_header(
    "Reproducción",
    "La sesión dibujada sobre cada pantalla, como un video: cursor, clics, scroll y mirada, con "
    "las tareas y los incidentes en la línea de tiempo. Debajo, cuánto coincide la mirada con los "
    "clics, para comprobar que la mirada funciona.",
)

#: Ancho con que se calcula la altura del reproductor en la página (diseño ancho de Streamlit).
PLAYER_WIDTH_PX = 1150
#: Alto de los controles y la franja de tiempo bajo la imagen.
CONTROLS_HEIGHT_PX = 110

with ui.selected_data() as data:
    study_id = ui.selected_study(data)
    sessions = data.get_sessions(study_id=study_id)
    if sessions.empty:
        st.caption("No hay sesiones en este estudio.")
        st.stop()
    session_id = ui.session_selector(sessions)
    session = data.get_session(session_id)
    events = data.get_events(session_id)
    gaze = data.get_gaze(session_id)
    payload = replay.build_payload(
        session,
        events,
        gaze,
        data.get_session_tasks(session_id),
        data.get_incidents(session_id=session_id),
        data.get_screen_captures(study_id),
    )
    calibrations = data.get_calibrations(session_id)

if not payload["images"]:
    st.info(
        "No hay capturas de las pantallas de este estudio: se dibuja sobre un fondo neutro. Para "
        "verlas de fondo, graba una referencia desde el panel lateral y pulsa "
        "**Capturar pantalla** "
        "en cada pantalla.",
        icon=":material/image:",
    )
width, height = payload["viewport"]
# El reproductor es HTML propio (dashboard/replay-player.html) con los datos de la sesión.
st.iframe(
    replay.player_html(payload), height=int(PLAYER_WIDTH_PX * height / width) + CONTROLS_HEIGHT_PX
)

# --- ¿La mirada mira lo que se pulsa? ---------------------------------------------------------
st.subheader("Mirada en cada clic")
clicks = int((events["type"] == "click").sum()) if not events.empty else 0
distances = replay.gaze_at_clicks(events, gaze)
summary = replay.agreement_summary(distances, clicks)
if summary["with_gaze"] == 0:
    st.caption(
        "Sin mirada válida cerca de los clics: la sesión no tiene cámara o no se calibró. "
        "La mirada "
        "solo es válida después de la calibración inicial."
    )
    st.stop()

camera = load_config().camera
measured = (
    calibrations["viewing_distance_cm"].dropna()
    if not calibrations.empty
    else pd.Series(dtype=float)
)
distance_cm = float(measured.iloc[0]) if len(measured) else camera.viewing_distance_cm
median_deg = math.degrees(math.atan(summary["median_px"] / camera.css_px_per_cm / distance_cm))
with_gaze, median, near = st.columns(3)
with_gaze.metric("Clics con mirada", f"{summary['with_gaze']} de {summary['clicks']}")
median.metric(
    "Distancia mediana mirada–clic",
    f"{ui.number(summary['median_px'], 0)} px",
    help=f"Unos {ui.number(median_deg, 1)}° de ángulo visual a {ui.number(distance_cm, 0)} cm.",
)
near.metric(
    f"Clics con la mirada a menos de {replay.NEAR_CLICK_PX} px",
    f"{ui.number(summary['near_share'] * 100, 0)} %",
)
st.caption(
    "Casi siempre se mira lo que se pulsa: si la distancia es chica, la mirada estimada es "
    "coherente con lo que hizo la persona. Se compara la mediana de la mirada entre 0,5 s antes y "
    "0,1 s después de cada clic."
)
with st.expander("Detalle por clic"):
    ui.show_table(distances.round(1))
