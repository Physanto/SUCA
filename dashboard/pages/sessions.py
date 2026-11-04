"""Página Sesiones: lista de sesiones del estudio, filtrable por versión y modo."""

import pandas as pd
import streamlit as st

from dashboard import ui

ui.page_header(
    "Sesiones",
    "Todas las sesiones del estudio, con su duración, incidentes, SUS e índice. Filtra por "
    "versión y modo; para ver una en detalle, ábrela en Sesión o en Reproducción.",
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

if not sessions.empty:
    guided = sessions[sessions["mode"] == "guided"]
    total, by_version, sus, index = st.columns(4)
    total.metric("Sesiones", len(sessions))
    by_version.metric(
        "Por versión",
        " · ".join(
            f"{version}: {count}"
            for version, count in sessions["version"].value_counts().sort_index().items()
        ),
    )
    sus.metric("SUS medio", ui.number(pd.to_numeric(guided["sus_score"]).mean()))
    index.metric("IUC medio", ui.number(pd.to_numeric(guided["bui"]).mean()))

ui.show_table(sessions, empty="No hay sesiones con esos filtros.")
