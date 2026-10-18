"""Página Índice: índice de usabilidad conductual (IUC) y SUS de cada sesión."""

from dashboard import ui

ui.page_header(
    "Índice",
    "IUC y sus componentes por sesión y por versión, y su relación con el SUS.",
)

with ui.selected_data() as data:
    index = data.get_usability_index(ui.selected_study(data))

ui.show_table(index, empty="Todavía no hay índices: analiza las sesiones guiadas.")
