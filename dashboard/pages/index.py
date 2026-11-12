"""Página Índice: IUC, sus componentes, el SUS interpretado y la relación entre ambos."""

import pandas as pd
import streamlit as st

from dashboard import charts, sus, ui

ui.page_header(
    "Índice",
    "IUC de cada sesión y sus cuatro componentes, por versión, el SUS interpretado y la relación "
    "entre ambos: el IUC complementa al cuestionario, no lo reemplaza.",
)


def show_sus(answers: pd.DataFrame) -> None:
    """El SUS por versión con su calificación, y qué ítems restaron más."""
    st.subheader("SUS")
    overall = sus.summarize(list(answers["score"]))
    if overall["rating"] is None:
        st.caption(overall["warning"])
        return
    groups = [("Todas", answers), *answers.groupby("version", sort=True)]
    for column, (name, group) in zip(st.columns(len(groups)), groups, strict=True):
        reading = sus.summarize(list(group["score"]))
        rating = reading["rating"]
        column.metric(
            f"SUS · {name}",
            ui.number(reading["mean"], 0),
            delta=f"{rating.label} ({rating.grade}) · {reading['mean'] - sus.AVERAGE_SUS:+.0f}",
            delta_color="off",
            help=f"{rating.versus_average} {reading['warning']}".strip(),
        )
    if overall["warning"]:
        st.caption(overall["warning"])
    st.caption(
        "Calificación según la literatura: Pobre (menos de 51), Aceptable, Bueno (desde 71) y "
        "Excelente (desde 86); el promedio histórico es 68. Debajo de la cifra: la calificación, "
        "la nota (A a F) y la diferencia con el promedio."
    )
    breakdown = sus.item_breakdown(answers)
    if not breakdown.empty:
        st.caption("Qué ítems restaron más (aporte medio de 0 a 4; 4 es lo mejor)")
        st.bar_chart(
            breakdown.assign(item=lambda t: t["item"].astype(str) + ". " + t["text"]).set_index(
                "item"
            )["mean"],
            horizontal=True,
        )


with ui.selected_data() as data:
    study_id = ui.selected_study(data)
    index = data.get_usability_index(study_id)
    answers = data.get_sus_answers(study_id)

if index.empty:
    st.caption("Todavía no hay índices: analiza las sesiones guiadas.")
    show_sus(answers)
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

show_sus(answers)
