"""Página Referencias: revisar la ruta grabada de cada tarea y confirmar su condición final.

Es la única página que escribe en la base (``DashboardData.confirm_reference``):
el evaluador elige, entre las candidatas que propuso el análisis, la condición
que indica que la tarea se completó, y marca los pasos que no pueden faltar.
Una referencia confirmada sirve para terminar las tareas solas en el modo
guiado y para comparar las rutas de los participantes.
"""

from typing import Any

import pandas as pd
import streamlit as st

from dashboard import heatmap, ui
from dashboard.data import InvalidReferenceError

ui.page_header(
    "Referencias",
    "Ruta grabada de cada tarea: revisa sus pasos, elige la condición final entre las candidatas y "
    "marca los pasos obligatorios. Al confirmar, la referencia queda lista para el modo guiado y "
    "el "
    "análisis.",
)

STEP_LABELS = {
    "click": "Clic",
    "form_submit": "Envío de formulario",
    "screen_change": "Cambio de pantalla",
}
STATUS_LABELS = {"draft": "Borrador", "confirmed": "Confirmada"}


def condition_label(condition: dict[str, Any] | None) -> str:
    """Una condición final en palabras."""
    if not condition:
        return "—"
    kind = condition.get("type")
    if kind == "url_pattern":
        return f"La dirección es {condition['pattern']}"
    if kind == "visible_text":
        return f"Se ve el texto «{condition['text']}»"
    if kind == "element_present":
        return f"Hay un elemento {condition['role']} «{condition['text']}»"
    return str(condition)


def steps_frame(steps: list[dict[str, Any]], required: list[int]) -> pd.DataFrame:
    """Los pasos de una referencia como tabla editable, con la marca de obligatorio."""
    rows = []
    for position, step in enumerate(steps):
        element = step.get("element") or {}
        rows.append(
            {
                "Obligatorio": position in required,
                "N.º": position + 1,
                "Paso": STEP_LABELS.get(step["type"], step["type"]),
                "Pantalla": heatmap.screen_key(step["screen"]["url"]),
                "Elemento": " · ".join(
                    str(part) for part in (element.get("role"), element.get("text")) if part
                )
                or "—",
            }
        )
    return pd.DataFrame(rows, columns=["Obligatorio", "N.º", "Paso", "Pantalla", "Elemento"])


with ui.selected_data() as data:
    references = data.get_references(ui.selected_study(data))
    if references.empty:
        st.caption(
            "El estudio no tiene referencias. Grábalas desde el panel lateral de la extensión, en "
            "modo Referencia, y analiza esa sesión."
        )
        st.stop()

    overview = references[
        ["reference_id", "position", "instruction", "status", "source_session_id"]
    ].copy()
    overview["status"] = overview["status"].map(lambda status: STATUS_LABELS.get(status, status))
    overview["end_condition"] = references["end_condition"].map(condition_label)
    overview["steps"] = references["steps"].map(len)
    ui.show_table(overview)

    labels = {
        int(row.reference_id): f"Tarea {row.position} · referencia {row.reference_id} · "
        f"{STATUS_LABELS.get(row.status, row.status)}"
        for row in references.itertuples()
    }
    reference_id = st.selectbox("Referencia", list(labels), format_func=labels.get)
    chosen = references.set_index("reference_id").loc[reference_id]
    st.markdown(f"**Tarea {chosen['position']}:** {chosen['instruction']}")

    steps = chosen["steps"] or []
    required = chosen["required_steps"] or []
    st.caption("Pasos grabados. Marca los que no pueden faltar en la ruta de un participante.")
    edited = st.data_editor(
        steps_frame(steps, required),
        hide_index=True,
        width="stretch",
        disabled=["N.º", "Paso", "Pantalla", "Elemento"],
        key=f"steps_{reference_id}",
    )

    candidates = chosen["candidates"] or []
    current = chosen["end_condition"]
    options = list(range(len(candidates)))
    default = candidates.index(current) if current in candidates else 0
    if not candidates:
        st.warning(
            "El análisis no propuso condiciones finales para esta referencia: analiza su sesión."
        )
        st.stop()
    picked = st.radio(
        "Condición final",
        options,
        index=default,
        format_func=lambda option: condition_label(candidates[option]),
        key=f"condition_{reference_id}",
    )
    if st.button("Confirmar referencia", type="primary"):
        positions = [int(number) - 1 for number in edited.loc[edited["Obligatorio"], "N.º"]]
        try:
            data.confirm_reference(int(reference_id), candidates[picked], positions)
        except InvalidReferenceError as error:
            st.error(f"No se pudo confirmar: {error}")
        else:
            st.success(
                f"Referencia {reference_id} confirmada: {condition_label(candidates[picked])}, "
                f"{len(positions)} paso(s) obligatorio(s)."
            )
