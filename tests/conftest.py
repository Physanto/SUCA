"""Fixtures comunes a varias carpetas de pruebas.

``mock`` genera una sola vez por corrida la base simulada completa, porque
validar todos sus registros con los contratos tarda unos segundos. La usan las
pruebas de los datos simulados y las del panel de resultados. Es de solo
lectura: una prueba que la modifica trabaja sobre una copia.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.generate_mock_data import generate


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
