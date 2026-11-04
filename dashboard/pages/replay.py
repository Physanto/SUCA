"""Página Reproducción: la sesión otra vez, sobre lo que se veía, y la prueba de la mirada.

No vuelve a ejecutar la prueba en el sitio: muestra las capturas tomadas durante
la sesión y dibuja encima lo capturado (cursor, clics, scroll, mirada, campos,
pantallas e incidentes), cada señal con su color, en el tiempo en que pasó.
"""

import math

import pandas as pd
import streamlit as st

from dashboard import replay, ui
from shared.config import load_config

ui.page_header(
    "Reproducción",
    "La sesión como un video sobre lo que se veía en la página: cursor, clics, scroll, mirada, "
    "campos y lo escrito en los campos declarados, cambios de pantalla e incidentes, cada uno con "
    "su color. Debajo, cuánto coincide la mirada con los clics, para comprobar que funciona.",
)

#: Ancho con que se calcula la altura del reproductor en la página (diseño ancho de Streamlit).
PLAYER_WIDTH_PX = 1150
#: Alto de los controles, las capas y la franja de tiempo bajo la imagen.
CONTROLS_HEIGHT_PX = 150
#: Más capturas que esto en un tramo hacen lenta la página: se sugiere elegir una tarea.
MANY_FRAMES = 300

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
    tasks = data.get_session_tasks(session_id)
    frames = data.get_session_frames(session_id)
    windows = [("Toda la sesión", None), *replay.task_windows(tasks)]
    # Con muchas capturas, se empieza por la primera tarea para que la página cargue rápido.
    default = 1 if len(frames) > MANY_FRAMES and len(windows) > 1 else 0
    names = [name for name, _ in windows]
    chosen = st.selectbox("Tramo", names, index=default)
    window = dict(windows)[chosen]
    payload = replay.build_payload(
        session,
        events,
        gaze,
        tasks,
        data.get_incidents(session_id=session_id),
        data.get_screen_captures(study_id),
        frames,
        window,
    )
    calibrations = data.get_calibrations(session_id)

if payload["frames"]:
    if len(payload["frames"]) > MANY_FRAMES:
        st.caption(
            f"Este tramo tiene {len(payload['frames'])} capturas y puede tardar en cargar: elige "
            "una tarea en **Tramo**."
        )
elif payload["images"]:
    st.info(
        "Esta sesión no tiene capturas propias (se grabó antes de que la extensión las tomara, o "
        "la pestaña no estaba activa): de fondo va la captura de referencia de cada pantalla, que "
        "no muestra lo que pasó en esta sesión.",
        icon=":material/image:",
    )
else:
    st.info(
        "No hay capturas de esta sesión ni de las pantallas del estudio: se dibuja sobre un fondo "
        "neutro.",
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
