"""Página Índice: índice de usabilidad conductual (IUC), sus componentes y su relación con SUS."""

import pandas as pd
import streamlit as st

from dashboard import charts, ui

ui.page_header(
    "Índice",
    "IUC de cada sesión y sus cuatro componentes, por versión, y su relación con el SUS: el IUC "
    "complementa al cuestionario, no lo reemplaza.",
)

with ui.selected_data() as data:
    index = data.get_usability_index(ui.selected_study(data))

if index.empty:
    st.caption("Todavía no hay índices: analiza las sesiones guiadas.")
    st.stop()

means = index.groupby("version")["bui"].mean()
columns = st.columns(len(means) + 1)
for column, (version, value) in zip(columns, means.items(), strict=False):
    column.metric(f"IUC medio · {version}", ui.number(value))
rho, count = charts.correlation(index)
columns[-1].metric(
    "Correlación IUC–SUS",
    "—" if rho is None else ui.number(rho, 2),
    help=f"Spearman con {count} sesiones con IUC y SUS. Con pocas sesiones no es concluyente.",
)

left, right = st.columns(2)
with left:
    st.caption("Componentes del índice (media por versión)")
    st.altair_chart(charts.index_components(index), width="stretch")
with right:
    st.caption("IUC frente a SUS")
    if pd.to_numeric(index["sus_score"]).notna().any():
        st.altair_chart(charts.bui_vs_sus(index), width="stretch")
    else:
        st.caption("Ninguna sesión tiene SUS todavía.")

ui.show_table(index)
