"""Página Tareas: resultados de cada tarea del estudio en las sesiones analizadas."""

from dashboard import ui

ui.page_header(
    "Tareas",
    "por tarea, tasa de éxito, tiempos, pasos y desvío más frecuente, con comparación entre "
    "versiones.",
)

with ui.selected_data() as data:
    results = data.get_task_results(ui.selected_study(data))

ui.show_table(results, empty="Todavía no hay resultados por tarea: analiza las sesiones guiadas.")
