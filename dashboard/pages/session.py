"""Página Sesión: lo que pasó en una sesión, en el tiempo y sobre cada pantalla."""

import pandas as pd
import streamlit as st
from PIL import Image

from dashboard import charts, heatmap, replay, ui

ui.page_header(
    "Sesión",
    "Línea de tiempo con tareas, pantallas, episodios, incidentes y clics; señal facial; "
    "mapas de calor de clics, cursor y mirada en cada pantalla; y los datos en tablas.",
)

with ui.selected_data() as data:
    study_id = ui.selected_study(data)
    sessions = data.get_sessions(study_id=study_id)
    if sessions.empty:
        st.caption("No hay sesiones en este estudio.")
        st.stop()
    session_id = ui.session_selector(sessions)
    session = data.get_session(session_id)
    tasks = data.get_session_tasks(session_id)
    incidents = data.get_incidents(session_id=session_id)
    episodes = data.get_episodes(session_id)
    events = data.get_events(session_id)
    gaze = data.get_gaze(session_id)
    face = data.get_face(session_id)
    calibrations = data.get_calibrations(session_id)
    captures = data.get_screen_captures(study_id)

summary = sessions.set_index("session_id").loc[session_id]
start = float(session["started_at"])

# --- Resumen -----------------------------------------------------------------------
duration, done, found, sus, index = st.columns(5)
duration.metric("Duración", ui.seconds(summary["duration_ms"]))
judged = tasks["success"].dropna() if not tasks.empty else tasks
if tasks.empty:
    done.metric("Tareas", "—")
elif len(judged):
    done.metric(
        "Tareas con éxito",
        f"{int(judged.astype(bool).sum())}/{len(tasks)}",
        help="Según el análisis.",
    )
else:
    done.metric(
        "Tareas hechas", len(tasks), help="Sin analizar todavía: no se sabe si tuvieron éxito."
    )
found.metric("Incidentes", len(incidents))
sus.metric("SUS", ui.number(summary["sus_score"]))
index.metric("IUC", ui.number(summary["bui"]))

if not calibrations.empty:
    columns = st.columns(len(calibrations["type"].unique()))
    for column, (kind, group) in zip(
        columns, calibrations.groupby("type", sort=False), strict=True
    ):
        last = group.iloc[-1]
        distance = last["viewing_distance_cm"]
        column.metric(
            "Calibración inicial" if kind == "initial" else "Comprobación final",
            ui.number(last["error_deg"], 2, "°"),
            help=(
                f"{len(group)} intento(s); {'aceptada' if last['accepted'] else 'no aceptada'}; "
                "distancia "
                f"{'sin medir' if pd.isna(distance) else ui.number(distance, 0, ' cm')}."
            ),
        )

# --- Línea de tiempo ------------------------------------------------------------------
st.subheader("Línea de tiempo")
st.altair_chart(charts.timeline(start, tasks, episodes, incidents, events), width="stretch")
if not face.empty and face["face_detected"].fillna(False).any():
    st.caption("Señal facial (media móvil de 1 s)")
    st.altair_chart(charts.face_signals(start, face), width="stretch", height=260)

# --- Mapas de calor -------------------------------------------------------------------
st.subheader("Mapas de calor")
layer = st.segmented_control(
    "Capa",
    list(heatmap.LAYERS),
    format_func=heatmap.LAYERS.get,
    default="click",
    key="session_layer",
)
located = heatmap.points(events, gaze, layer or "click")
visited = (
    heatmap.with_scroll(events[events["type"] == "screen_change"])["screen"]
    .drop_duplicates()
    .tolist()
    if not events.empty
    else []
)
if not visited:
    st.caption("La sesión no tiene pantallas.")
else:
    screen = st.selectbox("Pantalla", visited, key="session_screen")
    shots = captures[[heatmap.screen_key(url) == screen for url in captures["url"]]]
    background = Image.open(shots.iloc[-1]["absolute_path"]) if not shots.empty else None
    chosen = located[located["screen"] == screen][["x", "y"]].to_numpy()
    drawn = heatmap.render(
        chosen, layer=layer or "click", background=background, viewport=replay.viewport_of(session)
    )
    st.image(drawn.image, width="stretch")
    st.caption(
        f"{drawn.drawn} puntos dibujados"
        + (
            f"; {drawn.outside} quedaron fuera de la imagen (más abajo de la captura)"
            if drawn.outside
            else ""
        )
        + (
            "."
            if background is not None
            else ". Sin captura de esta pantalla: se dibuja sobre un fondo neutro."
        )
    )

# --- Datos ------------------------------------------------------------------------------
st.subheader("Datos")
tab_tasks, tab_incidents, tab_episodes, tab_events, tab_calibrations = st.tabs(
    ["Tareas", "Incidentes", "Episodios", "Eventos", "Calibraciones"]
)
with tab_tasks:
    ui.show_table(tasks, empty="La sesión no tiene tareas (no es guiada).")
with tab_incidents:
    shown = incidents.drop(columns=["session_id", "element"])
    shown["type"] = shown["type"].map(charts.incident_label)
    ui.show_table(shown, empty="Sin incidentes.")
with tab_episodes:
    ui.show_table(episodes, empty="Sin episodios: analiza la sesión.")
with tab_events:
    ui.show_table(events.drop(columns=["element", "data"]))
with tab_calibrations:
    ui.show_table(calibrations, empty="La sesión no tiene calibraciones.")
