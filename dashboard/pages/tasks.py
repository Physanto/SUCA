"""Página Tareas: éxito, tiempos, pasos y desvío de cada tarea, comparando versiones."""

import streamlit as st

from dashboard import charts, ui

ui.page_header(
    "Tareas",
    "Por tarea y versión: tasa de éxito, duración, pasos y el paso de la referencia en el que más "
    "se desvían las personas.",
)

with ui.selected_data() as data:
    results = data.get_task_results(ui.selected_study(data))

if results.empty:
    st.caption("Todavía no hay resultados por tarea: analiza las sesiones guiadas.")
    st.stop()

summary = charts.task_summary(results)
left, right = st.columns(2)
with left:
    st.caption("Tasa de éxito")
    st.altair_chart(charts.task_success(summary), width="stretch")
with right:
    st.caption("Duración de cada sesión")
    st.altair_chart(charts.task_durations(results), width="stretch")

st.subheader("Resumen por tarea y versión")
shown = summary.copy()
shown["success_rate"] = (shown["success_rate"] * 100).round(0)
ui.show_table(shown)

with st.expander("Resultados de cada sesión"):
    ui.show_table(results)
