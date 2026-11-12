"""Preparación de estudios reales con tareas explícitas y texto privado excluido."""

from pathlib import Path

import pytest

from scripts.load_study import read_study
from scripts.prepare_pilot import prepare


def test_generated_pilot_loads_without_recording_fields(tmp_path: Path) -> None:
    output = tmp_path / "pilot.yaml"
    prepare(
        "Aplicación del equipo",
        "https://example.org/#/catalog",
        ["Busca un elemento.", "Abre su detalle."],
        output,
    )
    document = read_study(output)
    assert document["system_under_test"] == "https://example.org/#/catalog"
    assert document["recorded_fields"] == []
    assert len(document["tasks"]) == 2
    with pytest.raises(FileExistsError):
        prepare("Otra", "https://example.org", ["Uno", "Dos"], output)


@pytest.mark.parametrize(
    "url,tasks",
    [
        ("file:///tmp/app", ["Uno", "Dos"]),
        ("https://user:secret@example.org", ["Uno", "Dos"]),
        ("https://example.org", ["Una sola"]),
        ("https://example.org", ["", "Dos"]),
    ],
)
def test_invalid_pilot_inputs_leave_no_file(tmp_path: Path, url: str, tasks: list[str]) -> None:
    output = tmp_path / "pilot.yaml"
    with pytest.raises(ValueError):
        prepare("Piloto", url, tasks, output)
    assert not output.exists()
