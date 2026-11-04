"""Pruebas del cargador de configuración ``shared.config``."""

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from shared.config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    ROOT_DIR,
    Config,
    ConfigError,
    load_config,
)

DEFAULT_DATA: dict[str, Any] = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(tmp_path: Path, **changes: Any) -> Path:
    """Escribe una copia de la configuración por defecto con cambios.

    Cada cambio se indica como ``seccion__clave=valor``; ``...`` borra la clave.
    """
    data = copy.deepcopy(DEFAULT_DATA)
    for dotted, value in changes.items():
        section, key = dotted.split("__")
        if value is ...:
            del data[section][key]
        else:
            data[section][key] = value
    path = tmp_path / "shared.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_default_configuration_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)

    config = load_config()

    assert isinstance(config, Config)
    assert config.server.host == "127.0.0.1"
    assert config.sending.interval_ms == 2000
    assert config.capture.mousemove_hz == 50
    assert config.capture.scroll_hz == 10
    assert config.capture.click_response_wait_ms == 1500


def test_camera_numbers_accept_integers_and_decimals(tmp_path: Path) -> None:
    """Las medidas de la cámara admiten 60 o 37.8 y siempre quedan como float."""
    config = load_config(
        write_config(tmp_path, camera__viewing_distance_cm=60, camera__css_px_per_cm=37.8)
    )

    assert config.camera.viewing_distance_cm == 60.0
    assert isinstance(config.camera.viewing_distance_cm, float)
    assert config.camera.css_px_per_cm == 37.8
    assert config.camera.calibration_max_error_deg == 5.0


def test_distance_scale_must_be_a_positive_number(tmp_path: Path) -> None:
    """La corrección de distancia de la webcam: 1 sin ajustar; nunca 0 ni negativa."""
    config = load_config(write_config(tmp_path, camera__distance_scale=1))

    assert config.camera.distance_scale == 1.0
    with pytest.raises(ConfigError, match="camera.distance_scale: must be positive"):
        load_config(write_config(tmp_path, camera__distance_scale=0))


def test_relative_paths_resolve_from_repository_root() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)

    assert config.database.path == ROOT_DIR / "data" / "suca.db"
    assert config.database.mock_path.is_absolute()


def test_absolute_paths_are_kept(tmp_path: Path) -> None:
    database = tmp_path / "other.db"

    config = load_config(write_config(tmp_path, database__path=str(database)))

    assert config.database.path == database


def test_configuration_is_immutable() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.server.port = 1  # type: ignore[misc]


def test_environment_variable_selects_another_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, str(write_config(tmp_path, server__port=9999)))

    assert load_config().server.port == 9999


def test_explicit_path_wins_over_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "missing.json"))

    assert load_config(DEFAULT_CONFIG_PATH).server.port == DEFAULT_DATA["server"]["port"]


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configuration file not found"):
        load_config(tmp_path / "missing.json")


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    path.write_text("{ server: }", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"server__token": ...}, r"server: missing keys \['token'\]"),
        ({"camera__fps": 30}, r"camera: unknown keys \['fps'\]"),
        ({"server__port": "8765"}, "server.port: expected an integer"),
        ({"sending__interval_ms": True}, "sending.interval_ms: expected an integer"),
        ({"capture__scroll_hz": 0}, "capture.scroll_hz: must be positive"),
        ({"server__port": 70000}, "server.port: must be between 1 and 65535"),
        ({"test_page__port": 65536}, "test_page.port: must be between 1 and 65535"),
        ({"test_app__port": 0}, "test_app.port: must be positive"),
        ({"test_app__port": 65536}, "test_app.port: must be between 1 and 65535"),
        ({"server__token": " "}, "server.token: expected a non-empty string"),
        ({"database__path": 3}, "database.path: expected a non-empty string"),
        ({"server__host": "0.0.0.0"}, "server.host: must be a loopback IP address"),
        ({"server__host": "localhost"}, "server.host: must be a loopback IP address"),
        ({"sending__retry_initial_ms": 60000}, "must not exceed sending.retry_max_ms"),
        ({"camera__css_px_per_cm": "37.8"}, "camera.css_px_per_cm: expected a number"),
        ({"camera__viewing_distance_cm": True}, "camera.viewing_distance_cm: expected a number"),
        ({"camera__calibration_max_error_deg": 0}, "must be positive"),
    ],
)
def test_invalid_values_are_reported_by_key(
    tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    path = write_config(tmp_path, **changes)

    with pytest.raises(ConfigError, match=message) as raised:
        load_config(path)

    assert str(path) in str(raised.value)


def test_missing_section_is_reported(tmp_path: Path) -> None:
    data = copy.deepcopy(DEFAULT_DATA)
    del data["camera"]
    path = tmp_path / "shared.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"configuration: missing keys \['camera'\]"):
        load_config(path)
