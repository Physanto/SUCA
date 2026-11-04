"""Los ejemplos de ``contracts/examples`` cumplen o incumplen sus contratos como dicen sus nombres.

Los ejemplos se llaman ``<kind>.valid.json`` o ``<kind>.invalid.<problema>.json``.
Cada ejemplo inválido tiene aquí el error que debe producir: ruta del campo y
un fragmento del motivo.
"""

import json
from pathlib import Path

import pytest

from shared import contracts

EXAMPLES = contracts.CONTRACTS_DIR / "examples"
VALID = sorted(EXAMPLES.glob("*.valid.json"))
INVALID = sorted(EXAMPLES.glob("*.invalid.*.json"))

EXPECTED_ERRORS: dict[str, tuple[tuple[str | int, ...], str]] = {
    "batch.invalid.empty-records.json": (("records",), "should be non-empty"),
    "batch.invalid.incompatible-contract-version.json": (("contract_version",), "does not match"),
    "batch.invalid.record-of-another-type.json": (
        ("records", 0, "valid"),
        "'valid' is a required property",
    ),
    "batch.invalid.unknown-type.json": (("type",), "'clicks' is not one of"),
    "calibration.invalid.negative-error.json": (("error_px",), "less than the minimum"),
    "element.invalid.input-with-text.json": (("text",), "is not of type 'null'"),
    "element.invalid.text-too-long.json": (("text",), "is too long"),
    "events.invalid.click-without-coordinates.json": (("x",), "'x' is a required property"),
    "events.invalid.field-change-text-without-field.json": (("data",), "'field' is a dependency"),
    "events.invalid.field-change-with-value.json": (("data",), "'value' was unexpected"),
    "events.invalid.timestamp-in-seconds.json": (("t",), "less than the minimum"),
    "events.invalid.unknown-event-type.json": (("type",), "'rageclick' is not one of"),
    "face.invalid.camel-case-face-value.json": (("values",), "'browDownLeft' is not one of"),
    "face.invalid.value-out-of-range.json": (
        ("values", "brow_inner_up"),
        "greater than the maximum",
    ),
    "gaze.invalid.valid-sample-without-zone.json": (("zone",), "None is not one of"),
    "new-capture.invalid.not-a-data-url.json": (("image",), "does not match"),
    "new-session.invalid.participant-name.json": (("participant_id",), "does not match"),
    "reference.invalid.screen-change-with-element.json": (
        ("steps", 1, "element"),
        "is not of type 'null'",
    ),
    "reference.invalid.unknown-end-condition-type.json": (
        ("end_condition", "type"),
        "'title_contains' is not one of",
    ),
    "reference.invalid.visible-text-without-text.json": (
        ("end_condition", "text"),
        "'text' is a required property",
    ),
    "study.invalid.task-without-instruction.json": (
        ("tasks", 1, "instruction"),
        "'instruction' is a required property",
    ),
    "sus-answers.invalid.nine-answers.json": (("answers",), "is too short"),
    "tasks.invalid.unknown-ended-by.json": (("ended_by",), "'timeout' is not one of"),
}


def kind_of(path: Path) -> str:
    """Devuelve el tipo de documento de un ejemplo a partir de su nombre."""
    return path.name.split(".", 1)[0]


def load(path: Path) -> object:
    """Lee un ejemplo."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_kind_has_a_valid_example() -> None:
    assert {kind_of(path) for path in VALID} == set(contracts.kinds())


def test_every_invalid_example_has_an_expected_error() -> None:
    assert {path.name for path in INVALID} == set(EXPECTED_ERRORS)


@pytest.mark.parametrize("path", VALID, ids=lambda path: path.name)
def test_valid_example_passes(path: Path) -> None:
    assert contracts.validate(kind_of(path), load(path)) == []


@pytest.mark.parametrize("path", INVALID, ids=lambda path: path.name)
def test_invalid_example_fails_with_expected_error(path: Path) -> None:
    expected_path, expected_reason = EXPECTED_ERRORS[path.name]

    errors = contracts.validate(kind_of(path), load(path))

    assert any(
        error.path == expected_path and expected_reason in error.message for error in errors
    ), [str(error) for error in errors]


def test_batch_example_covers_every_event_type() -> None:
    """El lote de ejemplo sirve de referencia para la captura: trae un evento de cada tipo."""
    batch = load(EXAMPLES / "batch.valid.json")

    assert {record["type"] for record in batch["records"]} == set(contracts.enums()["event_type"])
