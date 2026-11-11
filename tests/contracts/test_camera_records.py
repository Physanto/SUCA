"""Los registros que produce la cámara en la pestaña cumplen sus contratos.

``extension/tests/camera-records.js`` ejecuta el código real de la cámara con
cuadros variados (incluidos datos que el motor no debería enviar) y escribe un
ejemplo de cada registro. Aquí se validan con el validador de contratos, el
mismo que usa el servidor: así se comprueba que a los lotes ``gaze`` y ``face``
solo llegan números y campos del contrato, nunca imágenes ni datos de más.

Se salta si Node no está instalado.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from shared import contracts

SCRIPT = Path(__file__).resolve().parents[2] / "extension" / "tests" / "camera-records.js"


@pytest.fixture(scope="module")
def generated() -> dict[str, Any]:
    """Salida del generador: versión del contrato y registros por tipo de lote."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, str(SCRIPT)], capture_output=True, text=True, check=True, timeout=60
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "batch_type", ["gaze", "face", "gaze_features", "events", "calibration", "gaze_target"]
)
def test_camera_records_satisfy_their_contract(generated: dict[str, Any], batch_type: str) -> None:
    records = generated["batches"][batch_type]
    batch = {
        "contract_version": generated["contract_version"],
        "type": batch_type,
        "records": records,
    }

    assert records
    assert contracts.validate("batch", batch) == []


def test_face_and_gaze_samples_hold_only_numbers_and_contract_names(
    generated: dict[str, Any],
) -> None:
    """Fuera de la zona y del selector, todo valor es un número, un booleano o null."""
    textual = {"zone", "element_selector", "state"}
    for batch_type in ("gaze", "face", "gaze_features"):
        for record in generated["batches"][batch_type]:
            for key, value in record.items():
                if key == "values" and value is not None:
                    assert all(isinstance(v, int | float) for v in value.values())
                elif key not in textual:
                    assert value is None or isinstance(value, int | float | bool), (key, value)


def test_gaze_features_drop_what_the_engine_should_not_send(
    generated: dict[str, Any],
) -> None:
    """Un valor que no es del tipo del contrato queda en null y un campo extra no llega."""
    record = next(r for r in generated["batches"]["gaze_features"] if r["face_detected"])

    assert "iris_pixels" not in record
    assert record["right_h"] is None
    assert record["right_refined"] is None
    assert record["blink"] == 1


def test_calibrations_carry_the_estimator_and_the_drift_correction(
    generated: dict[str, Any],
) -> None:
    records = {r["type"]: r for r in generated["batches"]["calibration"]}

    assert records["initial"]["estimator"] == "geometric"
    assert records["initial"]["camera_delay_ms"] == 70
    assert records["drift_check"]["corrected"] is True
    assert records["drift_check"]["correction_x_px"] == -20


def test_every_kind_of_camera_gap_is_generated(generated: dict[str, Any]) -> None:
    """El ejemplo cubre el hueco que informa el motor y el de un motor reemplazado."""
    gaps = [e["data"] for e in generated["batches"]["events"] if e["type"] == "camera_gap"]

    assert {gap["reason"] for gap in gaps} == {"navigation", "error"}
