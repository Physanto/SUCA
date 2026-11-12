"""Página Hallazgos: qué problemas tuvo la gente, dónde, a cuántos afectó y qué revisar.

El sistema agrupa los incidentes y propone una gravedad y una explicación; el
evaluador las confirma en la reproducción, escribe la recomendación y las
conclusiones, y descarga el informe.
"""

import pandas as pd
import streamlit as st

from dashboard import facial_insights, findings, gaze_findings, ui

ui.page_header(
    "Hallazgos",
    "Los problemas que encontró el sistema, de más a menos graves: dónde pasaron, a cuántas "
    "personas afectaron y qué suelen indicar. Confirma cada uno en **Reproducción**, escribe la "
    "recomendación y descarga el informe.",
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
    sessions = every[every["mode"].isin(chosen_modes) & every["version"].isin(chosen_versions)]
    incidents = data.get_incidents(study_id=study_id)
    task_results = data.get_task_results(study_id)
    study_name = every["study"].iloc[0]
    references = data.get_references(study_id, status="confirmed")
    gaze_evidence = []
    facial_evidence, facial_missing = [], 0
    for sid in sessions["session_id"]:
        own = incidents[incidents["session_id"] == sid]
        if own.empty:
            continue
        gaze_evidence.append(
            gaze_findings.before_incidents(
                own,
                data.get_events(int(sid)),
                references,
                data.get_gaze_fixations(int(sid)),
                data.get_gaze_attribution(int(sid)),
                data.get_session_tasks(int(sid)),
            ).assign(session_id=sid)
        )
        session = data.get_session(int(sid))
        if session["ended_at"] is not None:
            try:
                facial_evidence.append(
                    facial_insights.incident_comparison(
                        data.get_face(int(sid)),
                        data.get_gaze_targets(int(sid)),
                        own,
                        float(session["started_at"]),
                        float(session["ended_at"]),
                    ).assign(Sesión=int(sid))
                )
            except ValueError:
                facial_missing += 1

if sessions.empty:
    st.caption("Elige al menos un modo y una versión con sesiones.")
    st.stop()

# --- Resumen ---------------------------------------------------------------------------------
st.subheader("Resumen por versión")
summary = findings.version_summary(sessions, task_results)
shown = summary.rename(
    columns={
        "version": "Versión",
        "sessions": "Sesiones",
        "success_rate": "Tareas completadas",
        "incidents_per_session": "Incidentes por sesión",
        "bui": "IUC",
        "sus": "SUS",
    }
)
shown["Tareas completadas"] = shown["Tareas completadas"].map(
    lambda value: None if value is None else round(value * 100)
)
st.dataframe(
    shown,
    hide_index=True,
    column_config={
        "Tareas completadas": st.column_config.NumberColumn(format="%d %%"),
        "Incidentes por sesión": st.column_config.NumberColumn(format="%.1f"),
        "IUC": st.column_config.NumberColumn(format="%.1f"),
        "SUS": st.column_config.NumberColumn(format="%.1f"),
    },
)
if summary["bui"].isna().all():
    st.caption(
        "Sin IUC: analiza las sesiones con `python -m analysis.run --study <id>`. Mientras el "
        "piloto no fije `friction_i_max`, el índice puede quedar vacío."
    )

# --- Hallazgos -------------------------------------------------------------------------------
st.subheader("Hallazgos")
found = findings.build_findings(incidents, sessions, task_results)
if found.empty:
    st.info("No hay incidentes en estas sesiones. ¿Ya se analizaron?", icon=":material/search:")
    st.stop()

counts = found["severity"].value_counts()
columns = st.columns(len(findings.SEVERITIES))
for column, severity in zip(columns, findings.SEVERITIES, strict=True):
    column.metric(f"Gravedad {severity.lower()}", int(counts.get(severity, 0)))
smallest = int(sessions.groupby("version")["session_id"].nunique().min())
if smallest < findings.FEW_SESSIONS:
    st.warning(
        f"Hay versiones con solo {smallest} sesión(es): la gravedad propuesta es poco fiable. "
        "Úsala como guía para revisar la reproducción, no como conclusión.",
        icon=":material/info:",
    )
st.caption(
    "**Gravedad propuesta:** alta si alguna persona afectada no completó la tarea, o si afectó a "
    "la mitad o más de las personas de esas versiones (al menos 2); media si afectó a un cuarto o "
    "más; si no, baja. Cámbiala "
    "si la reproducción muestra otra cosa. Un hallazgo que también aparece en la versión sin "
    "problemas (V0) puede ser una falsa alarma o un problema que nadie sembró."
)

# Nombres visibles de las columnas de los hallazgos.
LABELS = {
    "severity": "Gravedad",
    "screen": "Pantalla",
    "element": "Elemento",
    "incident": "Incidente",
    "people": "Personas",
    "share": "De las sesiones",
    "by_version": "Por versión",
    "failed_tasks": "No completaron",
    "also_in_baseline": "También en V0",
    "examples": "Dónde verlo",
    "recommendation": "Recomendación",
}

# La recomendación y la gravedad las edita el evaluador; se conservan mientras la página
# siga abierta con las mismas sesiones.
key = f"findings_{study_id}_{'-'.join(chosen_modes)}_{'-'.join(chosen_versions)}"
table = found.assign(recommendation="")[list(LABELS)].rename(columns=LABELS)
edited_view = st.data_editor(
    table,
    key=key,
    hide_index=True,
    width="stretch",
    disabled=[label for label in table.columns if label not in ("Gravedad", "Recomendación")],
    column_config={
        "Gravedad": st.column_config.SelectboxColumn(
            options=list(findings.SEVERITIES), required=True
        ),
        "De las sesiones": st.column_config.ProgressColumn(
            min_value=0.0, max_value=1.0, format="percent"
        ),
        "No completaron": st.column_config.NumberColumn(
            help="Personas afectadas que no completaron la tarea del incidente."
        ),
        "También en V0": st.column_config.CheckboxColumn(
            help="Aparece en la versión sin problemas sembrados."
        ),
        "Dónde verlo": st.column_config.TextColumn(
            help="Participante y minuto de la sesión, para buscarlo en Reproducción."
        ),
        "Recomendación": st.column_config.TextColumn(
            help="La escribes tú, después de verlo en Reproducción.", width="large"
        ),
    },
)
edited = found.assign(
    severity=edited_view["Gravedad"].to_numpy(),
    recommendation=edited_view["Recomendación"].fillna("").to_numpy(),
)

st.markdown("**Qué indica cada hallazgo**")
for index, row in enumerate(edited.head(10).itertuples(), start=1):
    with st.expander(f"{index}. {row.incident} en «{row.element}» · {row.screen} · {row.severity}"):
        st.markdown(f"**Qué suele indicar.** {row.meaning}")
        st.markdown(f"**Qué revisar.** {row.check}")
        st.markdown(
            f"**Dónde verlo.** {row.examples}. Abre **Reproducción**, elige la sesión y ve a ese "
            "minuto."
        )

with st.expander("¿Miró el siguiente elemento antes del incidente?"):
    st.caption(
        "Probabilidad aproximada en los 5 s previos, solo con mirada y secuencia; "
        "no usa clics ni focos. Cada referencia se muestra por separado. "
        "Sin captura atribuida se deja vacío. Las fijaciones vecinas no son independientes."
    )
    if gaze_evidence:
        shown_evidence = pd.concat(gaze_evidence, ignore_index=True)
        shown_evidence["p_seen"] = shown_evidence["p_seen"] * 100
        st.dataframe(
            shown_evidence.rename(
                columns={
                    "t": "Momento",
                    "type": "Incidente",
                    "task_id": "Tarea",
                    "reference_id": "Referencia",
                    "selector": "Elemento siguiente",
                    "p_seen": "Probabilidad (%)",
                    "fixations": "Fijaciones",
                    "reason": "Observación",
                    "session_id": "Sesión",
                }
            ),
            hide_index=True,
        )
    else:
        st.caption("Sin incidentes para consultar en estas sesiones.")

with st.expander("Movimientos faciales junto a incidentes y momentos de control"):
    st.caption(
        "Cambios respecto de los 10 s de rostro relajado de esa persona. Ventanas de 2 s; "
        "se excluyen pose extrema, captura insuficiente y calibraciones. Son movimientos "
        "observados: no se infieren emociones."
    )
    if facial_evidence:
        st.dataframe(pd.concat(facial_evidence, ignore_index=True), hide_index=True)
    if facial_missing:
        st.caption(f"{facial_missing} sesiones sin línea base facial utilizable.")

# --- Tareas ----------------------------------------------------------------------------------
st.subheader("Tareas")
tasks = findings.task_summary(task_results, incidents, sessions)
if tasks.empty:
    st.caption("Sin resultados por tarea: solo las sesiones guiadas analizadas los tienen.")
else:
    st.dataframe(
        tasks.assign(success_rate=tasks["success_rate"] * 100).rename(
            columns={
                "position": "Tarea",
                "instruction": "Instrucción",
                "success_rate": "Completada",
                "median_s": "Duración mediana",
                "main_incident": "Incidente más frecuente",
            }
        ),
        hide_index=True,
        column_config={
            "Completada": st.column_config.NumberColumn(format="%.0f %%"),
            "Duración mediana": st.column_config.NumberColumn(format="%.0f s"),
        },
    )

# --- Conclusiones e informe ------------------------------------------------------------------
st.subheader("Conclusiones")
conclusions = st.text_area(
    "Conclusiones del evaluador",
    key=f"{key}_conclusions",
    placeholder="Qué problemas hay que corregir primero y por qué; qué funcionó bien.",
    height=140,
)
report = findings.report_markdown(
    study_name, chosen_versions, summary, tasks, edited, conclusions=conclusions
)
st.download_button(
    "Descargar informe (Markdown)",
    report,
    file_name=f"hallazgos-{study_id}.md",
    mime="text/markdown",
    icon=":material/download:",
)
st.caption(
    "La recomendación, la gravedad y las conclusiones no se guardan en la base: descarga el "
    "informe antes de cerrar o recargar la página."
)
