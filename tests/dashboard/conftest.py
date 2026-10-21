"""Fixtures de las pruebas del panel de resultados.

Usan la base simulada (``mock``, en ``tests/conftest.py``): la de solo lectura
para las consultas y una copia para la confirmación de referencias.
"""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dashboard.data import DashboardData, open_data
from shared.config import DEFAULT_CONFIG_PATH


@pytest.fixture
def data(mock: Any) -> Iterator[DashboardData]:
    """Acceso de solo lectura a la base simulada."""
    with open_data(mock.path) as opened:
        yield opened


@pytest.fixture
def copy_path(mock: Any, tmp_path: Path) -> Path:
    """Copia de la base simulada, para las pruebas que escriben."""
    copy = tmp_path / "mock-copy.db"
    shutil.copy(mock.path, copy)
    return copy


@pytest.fixture
def writable(copy_path: Path) -> Iterator[DashboardData]:
    """Acceso a una copia de la base simulada."""
    with open_data(copy_path) as opened:
        yield opened


@pytest.fixture
def dashboard_config(
    copy_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    """Configuración en la que la base simulada es la copia y la real no existe."""
    config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    paths = {"real": tmp_path / "missing-real.db", "mock": copy_path}
    config["database"] = {"path": str(paths["real"]), "mock_path": str(paths["mock"])}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("SUCA_CONFIG", str(path))
    return paths
