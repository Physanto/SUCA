"""Pruebas del generador de la configuración de la extensión."""

from pathlib import Path

import pytest

from scripts import generate_config
from shared import contracts
from shared.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH, load_config


def test_generated_file_is_up_to_date() -> None:
    """Si falla, ejecuta ``python -m scripts.generate_config`` y versiona el resultado."""
    expected = generate_config.render(load_config(DEFAULT_CONFIG_PATH))

    assert generate_config.OUTPUT_PATH.read_text(encoding="utf-8") == expected


def test_extension_receives_only_its_sections() -> None:
    selected = generate_config.extension_config(load_config(DEFAULT_CONFIG_PATH))

    assert set(selected) == {"server", "sending", "capture", "camera"}


def test_extension_receives_contract_version_and_enums() -> None:
    selected = generate_config.extension_contracts()

    assert selected["version"] == contracts.contract_version()
    assert selected["enums"] == {name: list(values) for name, values in contracts.enums().items()}


def test_database_paths_never_reach_the_extension() -> None:
    rendered = generate_config.render(load_config(DEFAULT_CONFIG_PATH))

    assert "database" not in rendered
    assert "test_page" not in rendered
    assert "mock.db" not in rendered


def test_main_writes_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "config.generated.js"
    monkeypatch.setattr(generate_config, "OUTPUT_PATH", output)
    monkeypatch.setattr(generate_config, "ROOT_DIR", tmp_path)
    monkeypatch.setenv(CONFIG_ENV_VAR, str(DEFAULT_CONFIG_PATH))

    generate_config.main()

    assert output.read_bytes() == generate_config.render(load_config()).encode("utf-8")
