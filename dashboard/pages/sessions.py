"""Página Sesiones: lista de sesiones del estudio, filtrable por versión y modo."""

import streamlit as st

from dashboard import ui

ui.page_header(
    "Sesiones",
    "lista de las sesiones, filtrable por estudio, versión y modo, con su duración, "
    "incidentes, SUS e índice, y un enlace a cada sesión.",
)

with ui.selected_data() as data:
    study_id = ui.selected_study(data)
    everything = data.get_sessions(study_id=study_id)
    left, right = st.columns(2)
    versions = left.multiselect("Versión", sorted(everything["version"].unique()))
    modes = right.multiselect(
        "Modo", sorted(everything["mode"].unique()), format_func=ui.MODE_LABELS.get
    )
    sessions = data.get_sessions(study_id=study_id, versions=versions, modes=modes)

ui.show_table(sessions, empty="No hay sesiones con esos filtros.")
