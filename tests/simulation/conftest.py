"""Fixtures de las pruebas de los datos simulados.

``mock`` genera una sola vez por corrida la base simulada completa, porque
validar todos sus registros con los contratos tarda unos segundos.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from analysis.parameters import Parameters, load_parameters
from scripts.generate_mock_data import generate
from scripts.simulation import scenarios
from scripts.simulation.builder import Click, Element, FillForm, Screen
from shared import db


@dataclass(frozen=True)
class Mock:
    """Base simulada generada para las pruebas.

    Attributes:
        path: Archivo de la base.
        truth: Verdad de referencia escrita junto a ella.
    """

    path: Path
    truth: dict[str, Any]

    def session(self, key: str) -> dict[str, Any]:
        """Verdad de referencia de una sesión, por su nombre (``guided_v1``…)."""
        return next(item for item in self.truth["sessions"] if item["key"] == key)


@pytest.fixture(scope="session")
def mock(tmp_path_factory: pytest.TempPathFactory) -> Mock:
    """Base simulada con la semilla por defecto."""
    path = tmp_path_factory.mktemp("mock") / "mock.db"
    return Mock(path, generate(path))


@pytest.fixture
def mock_connection(mock: Mock) -> Iterator[sqlite3.Connection]:
    """Conexión de solo lectura a la base simulada."""
    with closing(db.open_database(mock.path)) as connection:
        yield connection


@pytest.fixture
def params() -> Parameters:
    """Parámetros por defecto."""
    return load_parameters()


@pytest.fixture
def context(params: Parameters) -> scenarios.StudyContext:
    """Contexto del estudio de ejemplo en una base nueva, con las referencias grabadas."""
    base = scenarios.StudyContext(study_id=1, task_ids=(1, 2, 3, 4), params=params)
    recording = scenarios.reference_recording(base)
    durations = {item.task_id: item.duration_ms for item in recording.references}
    return scenarios.StudyContext(1, (1, 2, 3, 4), params, reference_durations=durations)


class Shop:
    """Pantallas y elementos mínimos para probar el constructor."""

    HOME = Screen("https://shop.local/", "Inicio", "/")
    CART = Screen("https://shop.local/cart", "Carrito", "/cart")
    HELP = Screen("https://shop.local/help", "Ayuda", "/help")
    GO = Element("button", "go", "button", "Ir al carrito", "#go", (100, 200, 120, 40))
    HOME_LINK = Element("a", "home", "link", "Inicio", "#home", (20, 20, 60, 20))
    CART_LINK = Element("a", "cart", "link", "Carrito", "#cart", (200, 20, 60, 20))
    HELP_LINK = Element("a", "help", "link", "Ayuda", "#help", (300, 20, 60, 20))
    IMAGE = Element("img", "zoom", None, None, "#zoom", (400, 300, 80, 80), interactive=False)
    FORM = Element("form", "f", "form", None, "#f", (100, 400, 400, 200), interactive=False)
    NAME = Element("input", "name", "textbox", None, "#name", (110, 420, 200, 30))
    SEND = Element("button", "send", "button", "Enviar", "#send", (110, 470, 100, 30))
    PATH = (Click(GO, to=CART), FillForm(FORM, (NAME,), SEND, to=HOME, required=True))


@pytest.fixture
def shop() -> type[Shop]:
    """Tienda mínima para las pruebas del constructor."""
    return Shop
