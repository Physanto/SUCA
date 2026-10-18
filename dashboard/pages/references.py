"""Página Referencias: rutas grabadas de cada tarea y su condición final."""

from dashboard import ui

ui.page_header(
    "Referencias",
    "revisar los pasos grabados de cada tarea, elegir la condición final entre las candidatas "
    "y marcar los pasos obligatorios (con `DashboardData.confirm_reference`).",
)

with ui.selected_data() as data:
    references = data.get_references(ui.selected_study(data))

# Pasos y candidatas son listas largas: en la tabla mínima se muestra cuántos hay.
references["steps"] = references["steps"].map(len)
references["candidates"] = references["candidates"].map(len)
ui.show_table(references, empty="El estudio no tiene referencias grabadas.")
