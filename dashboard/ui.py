"""Ayudas de Streamlit que comparten la navegación y las páginas del panel.

- Elegir la base de datos (real o simulada) y el estudio, en la barra lateral.
- Abrir la base elegida con ``dashboard.data`` (``selected_data``).
- Mostrar tablas con las columnas en español, las fechas legibles y las
  duraciones en segundos (``show_table``).

``data.py`` no importa Streamlit; este módulo sí, y no tiene SQL.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.data import DashboardData, open_data
from shared import db
from shared.config import load_config

DATABASE_KEY = "database"
"""Clave de ``st.session_state`` con la base elegida (``real`` o ``mock``)."""

STUDY_KEY = "study_id"
"""Clave de ``st.session_state`` con el estudio elegido."""

DATABASE_LABELS: Mapping[str, str] = {"real": "Real", "mock": "Simulada"}
"""Bases que se pueden elegir y su etiqueta."""

MODE_LABELS: Mapping[str, str] = {"free": "Libre", "guided": "Guiado", "reference": "Referencia"}
"""Etiquetas de los modos de sesión."""

COLUMN_LABELS: Mapping[str, str] = {
    "session_id": "Sesión",
    "study_id": "Id del estudio",
    "study": "Estudio",
    "participant_id": "Participante",
    "version": "Versión",
    "mode": "Modo",
    "started_at": "Inicio",
    "ended_at": "Fin",
    "duration_ms": "Duración (s)",
    "incidents": "Incidentes",
    "sus_score": "SUS",
    "bui": "IUC",
    "task_id": "Tarea",
    "position": "N.º",
    "instruction": "Instrucción",
    "t": "Momento",
    "t_start": "Inicio",
    "t_end": "Fin",
    "ended_by": "Terminó por",
    "success": "Éxito",
    "steps": "Pasos",
    "deviation_step": "Paso de desvío",
    "off_path_ms": "Fuera de ruta (s)",
    "type": "Tipo",
    "screen": "Pantalla",
    "element": "Elemento",
    "outcome": "Resultado",
    "metrics": "Métricas",
    "visits": "Visitas",
    "sessions": "Sesiones",
    "time_ms": "Tiempo (s)",
    "effectiveness": "Efectividad",
    "time_efficiency": "Eficiencia temporal",
    "path_efficiency": "Eficiencia de ruta",
    "friction": "Fricción",
    "params_version": "Versión de parámetros",
    "reference_id": "Referencia",
    "status": "Estado",
    "source_session_id": "Sesión de origen",
    "end_condition": "Condición final",
    "required_steps": "Pasos obligatorios",
    "url": "URL",
    "title": "Título",
    "error_px": "Error (px)",
    "error_deg": "Error (°)",
    "accepted": "Aceptada",
    "viewing_distance_cm": "Distancia (cm)",
    "success_rate": "Éxito (%)",
    "median_duration_ms": "Duración mediana (s)",
    "median_steps": "Pasos (mediana)",
    "frequent_deviation": "Desvío más frecuente",
    "x": "x",
    "y": "y",
    "gaze_x": "Mirada x",
    "gaze_y": "Mirada y",
    "distance_px": "Distancia (px)",
}
"""Etiqueta en español de cada columna que devuelve ``dashboard.data``."""

#: Columnas con marcas de tiempo (ms desde 1970) y con duraciones en ms.
_TIME_COLUMNS = ("started_at", "ended_at", "t", "t_start", "t_end")
_DURATION_COLUMNS = ("duration_ms", "off_path_ms", "time_ms", "median_duration_ms")


def database_paths() -> dict[str, Path]:
    """Rutas de las bases que se pueden elegir, según la configuración.

    Returns:
        ``real`` → ``database.path``; ``mock`` → ``database.mock_path``.
    """
    config = load_config()
    return {"real": config.database.path, "mock": config.database.mock_path}


def _default_database(paths: Mapping[str, Path]) -> str:
    """La base real si existe; si no, la simulada."""
    return "real" if paths["real"].is_file() else "mock"


def database_selector() -> Path:
    """Muestra en la barra lateral la elección de base de datos.

    Returns:
        Ruta de la base elegida.
    """
    paths = database_paths()
    options = list(DATABASE_LABELS)
    choice = st.sidebar.radio(
        "Base de datos",
        options,
        index=options.index(_default_database(paths)),
        format_func=DATABASE_LABELS.get,
        captions=[str(paths[option]) for option in options],
        key=DATABASE_KEY,
    )
    return paths[choice]


def selected_path() -> Path:
    """Ruta de la base elegida en la barra lateral (o la de por defecto).

    Returns:
        Ruta de la base.
    """
    paths = database_paths()
    return paths[st.session_state.get(DATABASE_KEY) or _default_database(paths)]


@contextmanager
def selected_data() -> Iterator[DashboardData]:
    """Abre la base elegida; si no se puede, lo explica y detiene la página.

    Yields:
        Acceso a los datos de la base elegida.
    """
    path = selected_path()
    if not path.is_file():
        st.warning(
            f"No existe la base {path}. Crea la simulada con "
            "`python -m scripts.generate_mock_data`, o la real con `python -m scripts.init_db`."
        )
        st.stop()
    try:
        with open_data(path) as data:
            yield data
    except db.SchemaVersionError as error:
        st.error(f"La base {path} tiene otra versión del esquema: {error}")
        st.stop()


def study_selector() -> int | None:
    """Muestra en la barra lateral la elección de estudio de la base elegida.

    Returns:
        Id del estudio elegido, o ``None`` si la base no existe o no tiene estudios.
    """
    path = selected_path()
    if not path.is_file():
        return None
    with open_data(path) as data:
        studies = data.get_studies()
    if studies.empty:
        st.sidebar.info("La base no tiene estudios. Carga uno con `python -m scripts.load_study`.")
        return None
    names = {
        int(study_id): name for study_id, name in zip(studies["id"], studies["name"], strict=True)
    }
    if st.session_state.get(STUDY_KEY) not in names:
        st.session_state.pop(STUDY_KEY, None)
    return st.sidebar.selectbox("Estudio", list(names), format_func=names.get, key=STUDY_KEY)


def selected_study(data: DashboardData) -> int | None:
    """Estudio elegido en la barra lateral, o el primero de la base si no hay ninguno elegido.

    Args:
        data: Acceso a la base elegida.

    Returns:
        Id del estudio, o ``None`` si la base no tiene estudios.
    """
    chosen = st.session_state.get(STUDY_KEY)
    if chosen is not None:
        return chosen
    studies = data.get_studies()
    return None if studies.empty else int(studies["id"].iloc[0])


SESSION_KEY = "session_id"
"""Clave de ``st.session_state`` con la sesión elegida; la comparten Sesión y Reproducción."""


def page_header(title: str, description: str) -> None:
    """Título de una página y una línea que explica qué muestra.

    Args:
        title: Título.
        description: Qué muestra la página.
    """
    st.title(title)
    st.caption(description)


def session_label(row: Any) -> str:
    """Nombre de una sesión en los selectores: id, participante, versión y modo."""
    mode = MODE_LABELS.get(row.mode, row.mode)
    return f"{row.session_id} · {row.participant_id} · {row.version} · {mode}"


def session_selector(sessions: pd.DataFrame) -> int:
    """Elección de una sesión; recuerda la última elegida entre páginas.

    Args:
        sessions: ``DashboardData.get_sessions`` (no vacío).

    Returns:
        Id de la sesión elegida.
    """
    labels = {int(row.session_id): session_label(row) for row in sessions.itertuples()}
    if st.session_state.get(SESSION_KEY) not in labels:
        # Sin elección, la primera sesión guiada: es la que tiene más que mostrar.
        guided = sessions[sessions["mode"] == "guided"]["session_id"]
        st.session_state[SESSION_KEY] = int(
            guided.iloc[0] if len(guided) else sessions["session_id"].iloc[0]
        )
    return st.selectbox("Sesión", list(labels), format_func=labels.get, key=SESSION_KEY)


def seconds(ms: float | None) -> str:
    """Una duración en ms como texto (``1:05`` o ``—``)."""
    if ms is None or pd.isna(ms):
        return "—"
    total = int(round(float(ms) / 1000))
    return f"{total // 60}:{total % 60:02d}"


def number(value: float | None, digits: int = 1, suffix: str = "") -> str:
    """Un número con coma decimal, o ``—`` si falta."""
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}".replace(".", ",") + suffix


def show_table(df: pd.DataFrame, *, empty: str = "Todavía no hay datos.") -> None:
    """Muestra un DataFrame de ``dashboard.data`` con etiquetas en español.

    Las marcas de tiempo pasan a fecha y hora local; las duraciones, a segundos;
    los modos, a su etiqueta.

    Args:
        df: Datos a mostrar.
        empty: Mensaje si no hay filas.
    """
    if df.empty:
        st.caption(empty)
        return
    shown = df.copy()
    local = datetime.now().astimezone().tzinfo
    for column in _TIME_COLUMNS:
        if column in shown:
            shown[column] = pd.to_datetime(shown[column], unit="ms", utc=True).dt.tz_convert(local)
    for column in _DURATION_COLUMNS:
        if column in shown:
            # Una columna sin valores llega como object; to_numeric la deja en NaN.
            shown[column] = (pd.to_numeric(shown[column]) / 1000).round(1)
    if "mode" in shown:
        shown["mode"] = shown["mode"].map(lambda mode: MODE_LABELS.get(mode, mode))
    # Una etiqueta se usa una sola vez: si dos columnas la comparten, la segunda queda en inglés.
    labels: dict[str, str] = {}
    for column in shown.columns:
        label = COLUMN_LABELS.get(column, column)
        labels[column] = label if label not in labels.values() else column
    shown = shown.rename(columns=labels)
    st.dataframe(shown, hide_index=True, width="stretch")
