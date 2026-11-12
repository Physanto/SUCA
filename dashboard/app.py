"""Panel de resultados: navegación entre las páginas y elección de la base y el estudio.

Se ejecuta desde la raíz del repositorio con::

    streamlit run dashboard/app.py

En la barra lateral se elige la base (real o simulada) y el estudio; las
páginas los leen con ``dashboard.ui``.

Para agregar una página, crea su archivo en ``pages/`` y regístrala en
``PAGES``; la navegación no cambia.
"""

import streamlit as st

from dashboard import ui

# Páginas del panel, en el orden del menú: archivo (relativo a esta carpeta), título e ícono.
# Es un comentario y no un docstring: Streamlit mostraría en la página un texto suelto.
PAGES: tuple[tuple[str, str, str], ...] = (
    ("pages/sessions.py", "Sesiones", ":material/list:"),
    ("pages/session.py", "Sesión", ":material/timeline:"),
    ("pages/tasks.py", "Tareas", ":material/task_alt:"),
    ("pages/screens.py", "Pantallas", ":material/web:"),
    ("pages/index.py", "Índice", ":material/speed:"),
    ("pages/references.py", "Referencias", ":material/route:"),
    ("pages/replay.py", "Reproducción", ":material/play_circle:"),
    ("pages/findings.py", "Hallazgos", ":material/fact_check:"),
    ("pages/report.py", "Informe", ":material/description:"),
)

st.set_page_config(page_title="SUCA · Resultados", page_icon=":material/insights:", layout="wide")
navigation = st.navigation([st.Page(path, title=title, icon=icon) for path, title, icon in PAGES])
ui.database_selector()
ui.study_selector()
navigation.run()
