"""Catálogo de problemas sembrados."""

from pathlib import Path

import pytest

from shared.problems import CatalogError, load_catalog

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "studies" / "example-problems.yaml"


def test_the_example_catalog_has_the_eight_problems_of_the_test_app() -> None:
    catalog = load_catalog(EXAMPLE)
    assert [problem.number for problem in catalog.problems] == list(range(1, 9))
    assert [p.number for p in catalog.active("V1")] == [1, 2, 3, 4]
    assert len(catalog.active("V2")) == 8
    assert catalog.active("V0") == ()


def test_an_incident_matches_by_type_task_and_screen() -> None:
    problem = load_catalog(EXAMPLE).problems[0]  # Imagen que parece botón, tarea 2, /product/{id}
    assert problem.matches("dead_click", 2, "/product/{id}")
    assert not problem.matches("dead_click", 2, "/cart")
    assert not problem.matches("dead_click", 3, "/product/{id}")
    assert not problem.matches("form_error", 2, "/product/{id}")
    login = load_catalog(EXAMPLE).problems[6]  # Fuera de las tareas.
    assert login.matches("rage_click", None, "/login")
    assert not login.matches("rage_click", 1, "/login")


def test_problems_with_the_same_task_and_detectors_overlap() -> None:
    catalog = load_catalog(EXAMPLE)
    form = catalog.problems[3]
    assert catalog.overlapping(form, "V1") == ()
    assert catalog.overlapping(form, "V2") == (6,)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("problems: 3", "problems"),
        ("problems:\n  - {number: 1, key: a, name: a, versions: [V1]}", "detectors"),
        (
            "problems:\n  - {number: 1, key: a, name: a, versions: [V1], detectors: [frown]}",
            "unknown incident types",
        ),
        (
            "problems:\n  - {number: 1, key: a, name: a, versions: [V1], detectors: [dead_click]}\n"
            "  - {number: 1, key: b, name: b, versions: [V1], detectors: [dead_click]}",
            "unique",
        ),
        (
            "problems:\n  - {number: 1, key: a, name: a, versions: [V1], detectors: [dead_click],"
            " task: 0}",
            "task",
        ),
    ],
)
def test_an_invalid_catalog_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "catalog.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CatalogError, match=message):
        load_catalog(path)
