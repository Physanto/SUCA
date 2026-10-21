"""Coherencia entre los esquemas y ``contracts/enums.json``.

Los esquemas toman los valores permitidos de ``enums.json`` con ``$ref``, así que
no pueden desincronizarse. Estas pruebas cuidan lo que ``$ref`` no garantiza:
que ningún esquema defina valores propios y que las reglas por tipo (ramas
``if``/``then``) cubran exactamente los valores de cada enumeración.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest

from shared import contracts

CONTRACTS = contracts.CONTRACTS_DIR
ENUMS = contracts.enums()


def load(relative: str) -> dict[str, Any]:
    """Lee un archivo de contratos."""
    return json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))


def schema_files() -> list[str]:
    """Rutas relativas de todos los esquemas y definiciones, salvo enums.json."""
    return sorted(
        path.relative_to(CONTRACTS).as_posix()
        for path in CONTRACTS.rglob("*.json")
        if path.relative_to(CONTRACTS).parts[0] != "examples" and path.name != "enums.json"
    )


def walk(node: Any, inside_if: bool = False) -> Iterator[tuple[str, Any, bool]]:
    """Recorre un esquema y devuelve cada palabra clave, su valor y si está dentro de un ``if``."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value, inside_if
            yield from walk(value, inside_if or key == "if")
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, inside_if)


def branch_values(all_of: list[dict[str, Any]], prop: str = "type") -> list[str]:
    """Valores de ``prop`` que seleccionan cada rama ``if``/``then`` de un ``allOf``."""
    values: list[str] = []
    for branch in all_of:
        condition = branch["if"]["properties"].get(prop)
        if condition is None:
            continue
        values.extend([condition["const"]] if "const" in condition else condition["enum"])
    return values


@pytest.mark.parametrize("relative", schema_files())
def test_schemas_define_no_values_of_their_own(relative: str) -> None:
    """Fuera de las condiciones ``if``, los valores permitidos solo llegan por ``$ref``."""
    own_values = [
        value for key, value, inside_if in walk(load(relative)) if key == "enum" and not inside_if
    ]

    assert own_values == []


@pytest.mark.parametrize("relative", schema_files())
def test_enum_references_exist(relative: str) -> None:
    refs = [value for key, value, _ in walk(load(relative)) if key == "$ref"]
    names = [ref.split("enums.json#/$defs/", 1)[1] for ref in refs if "enums.json#" in ref]

    assert set(names) <= set(ENUMS)


def test_every_batch_type_has_a_schema_and_a_branch() -> None:
    schema_types = {path.name.removesuffix(".schema.json") for path in CONTRACTS.glob("batches/*")}
    envelope = load("batch.schema.json")

    assert schema_types == set(ENUMS["batch_type"])
    assert sorted(branch_values(envelope["allOf"])) == sorted(ENUMS["batch_type"])
    for branch in envelope["allOf"]:
        batch_type = branch["if"]["properties"]["type"]["const"]
        items = branch["then"]["properties"]["records"]["items"]
        assert items == {"$ref": f"batches/{batch_type}.schema.json"}


def test_every_event_type_has_exactly_one_branch() -> None:
    schema = load("batches/events.schema.json")

    assert sorted(branch_values(schema["allOf"])) == sorted(ENUMS["event_type"])


def test_every_end_condition_type_has_exactly_one_branch() -> None:
    end_condition = load("reference.schema.json")["$defs"]["end_condition"]

    assert sorted(branch_values(end_condition["allOf"])) == sorted(ENUMS["end_condition_type"])


def test_every_step_type_has_exactly_one_branch_and_is_an_event_type() -> None:
    step = load("reference.schema.json")["$defs"]["step"]

    assert sorted(branch_values(step["allOf"])) == sorted(ENUMS["step_type"])
    assert set(ENUMS["step_type"]) <= set(ENUMS["event_type"])


def test_enum_values_are_unique() -> None:
    for name, values in ENUMS.items():
        assert len(values) == len(set(values)), name


def test_every_message_type_is_documented() -> None:
    text = (CONTRACTS / "extension-messages.md").read_text(encoding="utf-8")
    documented = re.findall(r"^### `([^`]+)`$", text, flags=re.MULTILINE)

    assert sorted(documented) == sorted(ENUMS["message_type"])
