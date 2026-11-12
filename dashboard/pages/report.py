"""Página Informe: el informe de resultados redactado, con gráficas, listo para descargar.

Junta en un documento lo que muestran las demás páginas: la lectura general
(SUS, tareas, IUC, hallazgos), el SUS por ítem, los hallazgos con su explicación,
los mapas de calor, la línea de tiempo y los indicios de las heurísticas de Nielsen.
El evaluador revisa la gravedad, escribe la recomendación de cada hallazgo y las
conclusiones, y descarga un único archivo HTML que se abre sin internet.
"""

import dataclasses

import streamlit as st
import streamlit.components.v1 as components

from dashboard import findings, report, report_inputs, ui

ui.page_header(
    "Informe",
    "El informe de resultados en un solo documento: lectura general, SUS, hallazgos, mapas de "
    "calor y línea de tiempo. Revisa la gravedad, escribe las recomendaciones y descárgalo.",
)

with ui.selected_data() as data:
    study_id = ui.selected_study(data)
    every = data.get_sessions(study_id=study_id)
    if every.empty:
        st.caption("No hay sesiones en este estudio.")
        st.stop()
    modes = sorted(every["mode"].unique())
    left, right = st.columns(2)
    chosen_modes = left.multiselect(
        "Modos",
        modes,
        default=["guided"] if "guided" in modes else modes,
        help="Las sesiones de referencia son la ruta ideal: normalmente no se incluyen.",
    )
    versions = sorted(every.loc[every["mode"].isin(chosen_modes), "version"].unique())
    chosen_versions = right.multiselect("Versiones", versions, default=versions)
    if not chosen_modes or not chosen_versions:
        st.caption("Elige al menos un modo y una versión.")
        st.stop()
    key = f"report_{study_id}_{'-'.join(chosen_modes)}_{'-'.join(chosen_versions)}"
    conclusions = st.text_area(
        "Conclusiones del evaluador",
        key=f"{key}_conclusions",
        placeholder="Qué hay que corregir primero y por qué; qué funcionó bien.",
        height=120,
    )
    with st.spinner("Armando el informe…"):
        inputs = report_inputs.collect(
            data,
            study_id,
            chosen_modes,
            chosen_versions,
            source=ui.selected_path().name,
            conclusions=conclusions,
        )

if inputs.findings.empty:
    st.info("No hay incidentes en estas sesiones. ¿Ya se analizaron?", icon=":material/search:")
else:
    st.markdown("**Gravedad y recomendación de los hallazgos principales**")
    st.caption(
        "Cambia la gravedad si la reproducción muestra otra cosa y escribe qué recomiendas. "
        "Se incluyen en el informe."
    )
    top = inputs.findings.head(report.TOP_FINDINGS)
    table = top[["severity", "incident", "element", "screen", "people", "recommendation"]].rename(
        columns={
            "severity": "Gravedad",
            "incident": "Incidente",
            "element": "Elemento",
            "screen": "Pantalla",
            "people": "Personas",
            "recommendation": "Recomendación",
        }
    )
    edited = st.data_editor(
        table,
        key=f"{key}_editor",
        hide_index=True,
        width="stretch",
        disabled=["Incidente", "Elemento", "Pantalla", "Personas"],
        column_config={
            "Gravedad": st.column_config.SelectboxColumn(
                options=list(findings.SEVERITIES), required=True
            ),
            "Recomendación": st.column_config.TextColumn(width="large"),
        },
    )
    reviewed = inputs.findings.copy()
    reviewed.loc[top.index, "severity"] = edited["Gravedad"].to_numpy()
    reviewed.loc[top.index, "recommendation"] = edited["Recomendación"].fillna("").to_numpy()
    inputs = dataclasses.replace(inputs, findings=reviewed)

html = report.render(inputs)
st.download_button(
    "Descargar informe (HTML)",
    html,
    file_name=f"informe-estudio-{study_id}.html",
    mime="text/html",
    icon=":material/download:",
    type="primary",
)
st.caption(
    "El archivo se abre en cualquier navegador sin internet y se imprime a PDF desde ahí. "
    "Contiene datos de participantes y capturas: guárdalo en local y no lo subas. Las "
    "recomendaciones y conclusiones no se guardan en la base: descarga antes de recargar."
)
components.html(html, height=900, scrolling=True)
