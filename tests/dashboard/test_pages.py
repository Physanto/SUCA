"""Pruebas de la navegación y de las páginas del panel, sin navegador.

Usan ``AppTest`` de Streamlit sobre una copia de la base simulada. Con
``st.navigation``, ``AppTest`` no vuelve a ejecutar ``app.py`` al cambiar de
página, así que cada página se prueba ejecutándola directamente.
"""

import re
import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from shared.config import ROOT_DIR

DASHBOARD = ROOT_DIR / "dashboard"
REGISTERED = re.findall(r'"pages/(\w+)\.py"', (DASHBOARD / "app.py").read_text(encoding="utf-8"))
TITLES = {
    "sessions": "Sesiones",
    "session": "Sesión",
    "tasks": "Tareas",
    "screens": "Pantallas",
    "index": "Índice",
    "references": "Referencias",
    "replay": "Reproducción",
    "findings": "Hallazgos",
}


def run(script: Path, **state: object) -> AppTest:
    """Ejecuta un script del panel con un estado de sesión inicial."""
    app = AppTest.from_file(str(script), default_timeout=60)
    for key, value in state.items():
        app.session_state[key] = value
    return app.run()


def test_every_page_of_the_architecture_is_registered() -> None:
    files = {path.stem for path in (DASHBOARD / "pages").glob("*.py")}

    assert REGISTERED == list(TITLES)
    assert set(REGISTERED) == files


def test_the_app_opens_on_the_mock_database_when_there_is_no_real_one(
    dashboard_config: dict[str, Path],
) -> None:
    app = run(DASHBOARD / "app.py")

    assert not app.exception
    assert app.sidebar.radio[0].value == "mock"
    assert app.sidebar.selectbox[0].label == "Estudio"
    assert [title.value for title in app.title] == ["Sesiones"]
    assert len(app.dataframe[0].value) == 5


@pytest.mark.parametrize("page", list(TITLES))
def test_each_page_shows_its_title_description_and_its_data(
    dashboard_config: dict[str, Path], page: str
) -> None:
    # La sesión 3 es guiada, en V1, con mirada: tiene datos en todas las páginas.
    app = run(DASHBOARD / "pages" / f"{page}.py", database="mock", study_id=1, session_id=3)

    assert not app.exception
    assert [title.value for title in app.title] == [TITLES[page]]
    assert app.caption[0].value
    assert app.dataframe and len(app.dataframe[0].value) > 0
    # Todas las columnas que muestran las páginas están en español.
    for table in app.dataframe:
        assert not [name for name in table.value.columns if "_" in name], page


def test_a_missing_database_is_explained(dashboard_config: dict[str, Path]) -> None:
    app = run(DASHBOARD / "pages" / "sessions.py", database="real")

    assert not app.exception
    assert "No existe la base" in app.warning[0].value
    assert str(dashboard_config["real"]) in app.warning[0].value


def test_the_panel_only_listens_on_this_computer() -> None:
    config = tomllib.loads((ROOT_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    assert config["server"]["address"] == "127.0.0.1"
    assert config["browser"]["gatherUsageStats"] is False
