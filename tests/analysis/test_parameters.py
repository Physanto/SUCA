"""Pruebas de la carga y validación de ``analysis/parameters.yaml``."""

import dataclasses
from pathlib import Path
from typing import Any

import pytest
import yaml

from analysis.parameters import DEFAULT_PARAMETERS_PATH, ParametersError, load_parameters
from shared.config import load_config


def default_data() -> dict[str, Any]:
    """Contenido del archivo por defecto, como diccionario."""
    return yaml.safe_load(DEFAULT_PARAMETERS_PATH.read_text(encoding="utf-8"))


def write(tmp_path: Path, data: Any) -> Path:
    """Escribe un archivo de parámetros y devuelve su ruta."""
    path = tmp_path / "parameters.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def changed(key: str, value: Any) -> dict[str, Any]:
    """Parámetros por defecto con una clave (``a.b`` para anidadas) cambiada."""
    data = default_data()
    *parents, last = key.split(".")
    node = data
    for parent in parents:
        node = node[parent]
    node[last] = value
    return data


def test_loads_the_default_parameters() -> None:
    params = load_parameters()

    assert params.version == "pilot-1"
    assert (params.rage_click.min_clicks, params.rage_click.window_ms) == (3, 1000)
    assert params.rage_click.radius_px == 30
    assert params.dead_click.wait_ms == 1500
    assert (params.long_pause_ms, params.hesitation_ms) == (5000, 2000)
    assert params.navigation_loop_window == 3
    assert (params.repeated_search.min_searches, params.repeated_search.window_ms) == (2, 60000)
    assert params.task_overtime_factor == 3.0
    assert params.friction_i_max is None
    assert params.camera_delay_ms == 0.0


def test_parameters_are_immutable() -> None:
    params = load_parameters()

    with pytest.raises(dataclasses.FrozenInstanceError):
        params.version = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.rage_click.window_ms = 1  # type: ignore[misc]


def test_dead_click_wait_fits_in_the_capture_window() -> None:
    """La captura solo observa la página ``click_response_wait_ms`` después de un clic."""
    params = load_parameters()

    assert params.dead_click.wait_ms <= load_config().capture.click_response_wait_ms


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("friction_i_max", 1.8),
        ("camera_delay_ms", 35.5),
        ("task_overtime_factor", 2.5),
        ("version", "final-1"),
    ],
)
def test_accepts_valid_values(tmp_path: Path, key: str, value: Any) -> None:
    params = load_parameters(write(tmp_path, changed(key, value)))

    assert getattr(params, key) == value


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("rage_click.min_clicks", 0, "rage_click.min_clicks: must be positive"),
        ("long_pause_ms", -1, "long_pause_ms: must be positive"),
        ("hesitation_ms", True, "hesitation_ms: expected a number"),
        ("dead_click.wait_ms", 1.5, "dead_click.wait_ms: expected an integer"),
        ("long_pause_ms", "5000", "long_pause_ms: expected a number"),
        ("version", "", "version: expected a non-empty string"),
        ("version", 1, "version: expected a non-empty string"),
        ("friction_i_max", 0, "friction_i_max: must be positive"),
        ("camera_delay_ms", -10, "camera_delay_ms: must be zero or positive"),
        ("rage_click", 3, "rage_click: expected a mapping"),
    ],
)
def test_rejects_invalid_values(tmp_path: Path, key: str, value: Any, message: str) -> None:
    with pytest.raises(ParametersError, match=message):
        load_parameters(write(tmp_path, changed(key, value)))


def test_rejects_missing_and_unknown_keys(tmp_path: Path) -> None:
    missing = default_data()
    del missing["long_pause_ms"]
    unknown = changed("rage_click.max_clicks", 9)

    with pytest.raises(ParametersError, match=r"parameters: missing keys \['long_pause_ms'\]"):
        load_parameters(write(tmp_path, missing))
    with pytest.raises(ParametersError, match=r"rage_click: unknown keys \['max_clicks'\]"):
        load_parameters(write(tmp_path, unknown))


def test_reports_missing_and_malformed_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("rage_click: [unclosed", encoding="utf-8")

    with pytest.raises(ParametersError, match="parameters file not found"):
        load_parameters(tmp_path / "missing.yaml")
    with pytest.raises(ParametersError, match="invalid YAML"):
        load_parameters(broken)
    with pytest.raises(ParametersError, match="expected a mapping"):
        load_parameters(write(tmp_path, ["not", "a", "mapping"]))
