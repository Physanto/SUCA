"""Página Sesión: lo que pasó en una sesión, con sus tareas, incidentes, episodios y eventos."""

import pandas as pd
import streamlit as st

from dashboard import ui

ui.page_header(
    "Sesión",
    "línea de tiempo de la sesión con tareas, eventos, incidentes, episodios y señal facial, "
    "y mapa de calor de clics, cursor y mirada por pantalla.",
)

with ui.selected_data() as data:
    sessions = data.get_sessions(study_id=ui.selected_study(data))
    if sessions.empty:
        st.caption("No hay sesiones en este estudio.")
        st.stop()
    labels = {
        row.session_id: f"{row.session_id} · {row.participant_id} · {row.version} · "
        f"{ui.MODE_LABELS.get(row.mode, row.mode)}"
        for row in sessions.itertuples()
    }
    session_id = st.selectbox("Sesión", list(labels), format_func=labels.get)
    tasks = data.get_session_tasks(session_id)
    incidents = data.get_incidents(session_id=session_id)
    episodes = data.get_episodes(session_id)
    events = data.get_events(session_id)

summary = sessions.set_index("session_id").loc[session_id]
first, second, third = st.columns(3)
first.metric("Eventos", len(events))
second.metric("Incidentes", len(incidents))
third.metric("IUC", "—" if pd.isna(summary["bui"]) else f"{summary['bui']:.1f}")

tab_tasks, tab_incidents, tab_episodes, tab_events = st.tabs(
    ["Tareas", "Incidentes", "Episodios", "Eventos"]
)
with tab_tasks:
    ui.show_table(tasks, empty="La sesión no tiene tareas (no es guiada).")
with tab_incidents:
    ui.show_table(incidents.drop(columns=["session_id", "element"]))
with tab_episodes:
    ui.show_table(episodes)
with tab_events:
    ui.show_table(events.drop(columns=["element", "data"]))
