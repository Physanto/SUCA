"""Pruebas de la fachada de validación ``shared.contracts``."""

import json

import pytest

from shared import contracts
from shared.contracts import ContractError, UnknownContractError

EXAMPLES = contracts.CONTRACTS_DIR / "examples"


def load_example(name: str) -> dict:
    """Lee un ejemplo de ``contracts/examples``."""
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_kinds_are_derived_from_schema_files() -> None:
    assert contracts.kinds() == (
        "batch",
        "calibration",
        "element",
        "events",
        "face",
        "gaze",
        "reference",
        "study",
        "tasks",
    )


def test_valid_document_has_no_errors() -> None:
    assert contracts.validate("batch", load_example("batch.valid.json")) == []


def test_unknown_kind_raises_with_available_kinds() -> None:
    with pytest.raises(UnknownContractError, match="expected one of"):
        contracts.validate("clicks", {})


def test_errors_carry_path_and_reason() -> None:
    batch = load_example("batch.valid.json")
    del batch["records"][3]["x"]

    errors = contracts.validate("batch", batch)

    assert errors == [ContractError(path=("records", 3), message="'x' is a required property")]
    assert str(errors[0]) == "records/3: 'x' is a required property"


def test_root_error_is_printed_as_root() -> None:
    assert str(ContractError(path=(), message="boom")) == "<root>: boom"


def test_nullable_field_reports_the_real_problem() -> None:
    """En un campo que admite null, el error no debe ser 'no es null'."""
    event = load_example("events.valid.json")
    event["element"]["text"] = "x" * 51

    [error] = contracts.validate("events", event)

    assert error.path == ("element", "text")
    assert "is too long" in error.message


def test_errors_are_sorted_by_numeric_position() -> None:
    batch = load_example("batch.valid.json")
    del batch["records"][10]["element"]
    del batch["records"][2]["x"]

    errors = contracts.validate("batch", batch)

    assert [error.path for error in errors] == [("records", 2), ("records", 10)]


def test_enums_are_read_only_tuples() -> None:
    values = contracts.enums()

    assert values["session_mode"] == ("free", "guided", "reference")
    with pytest.raises(TypeError):
        values["session_mode"] = ("free",)  # type: ignore[index]


def test_contract_version_is_semantic_and_used_by_examples() -> None:
    version = contracts.contract_version()

    assert version.count(".") == 2
    assert load_example("batch.valid.json")["contract_version"] == version
