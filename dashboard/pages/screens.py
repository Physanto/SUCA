"""Página Pantallas: tiempo e incidentes por pantalla normalizada del estudio."""

from dashboard import ui

ui.page_header(
    "Pantallas",
    "fricción, tiempo e incidentes por pantalla y por componente, para ver dónde están los "
    "problemas del sistema evaluado.",
)

with ui.selected_data() as data:
    screens = data.get_screen_summary(ui.selected_study(data))

ui.show_table(screens, empty="Todavía no hay pantallas: analiza las sesiones.")
