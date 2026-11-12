"""Pruebas de los hallazgos del panel (``dashboard.findings``), sin Streamlit."""

import pandas as pd
import pytest

from dashboard import charts, findings
from shared import contracts

BUTTON = {"text": "Agregar al carrito", "selector": "#add"}
IMAGE = {"text": None, "selector": "#zoom-badge"}


def sessions() -> pd.DataFrame:
    """Cuatro sesiones guiadas: dos en V0 y dos en V2, todas empezando en 0 ms."""
    return pd.DataFrame(
        {
            "session_id": [1, 2, 3, 4],
            "participant_id": ["P01", "P02", "P03", "P04"],
            "version": ["V0", "V0", "V2", "V2"],
            "started_at": [0.0, 0.0, 0.0, 0.0],
            "incidents": [0, 1, 3, 1],
            "bui": [95.0, 90.0, 60.0, None],
            "sus_score": [85.0, 80.0, 55.0, 60.0],
        }
    )


def incidents() -> pd.DataFrame:
    """Clics de frustración en el botón (V2, dos personas) y un clic sin respuesta en V0 y V2."""
    rows = [
        (3, "rage_click", 61000.0, "/product/{id}", 2, BUTTON),
        (3, "rage_click", 65000.0, "/product/{id}", 2, BUTTON),
        (4, "rage_click", 30000.0, "/product/{id}", 2, BUTTON),
        (2, "dead_click", 5000.0, "/product/{id}", 1, IMAGE),
        (3, "dead_click", 9000.0, "/product/{id}", 1, IMAGE),
        (9, "dead_click", 1000.0, "/product/{id}", 1, IMAGE),  # sesión no elegida
    ]
    return pd.DataFrame(rows, columns=["session_id", "type", "t", "screen", "task_id", "element"])


def task_results() -> pd.DataFrame:
    """La persona P03 no completó la tarea 2; las demás sí."""
    rows = []
    for session_id, version in [(1, "V0"), (2, "V0"), (3, "V2"), (4, "V2")]:
        for task_id, position in [(1, 1), (2, 2)]:
            success = not (session_id == 3 and task_id == 2)
            rows.append((session_id, version, task_id, position, f"Tarea {position}", success))
    frame = pd.DataFrame(
        rows, columns=["session_id", "version", "task_id", "position", "instruction", "success"]
    )
    frame["duration_ms"] = [20000.0, 30000.0, 22000.0, 34000.0, 25000.0, 90000.0, 21000.0, 70000.0]
    return frame


def test_findings_group_incidents_by_screen_element_and_type() -> None:
    found = findings.build_findings(incidents(), sessions(), task_results())

    rage, dead = found.iloc[0], found.iloc[1]
    assert (rage["incident"], rage["element"], rage["people"], rage["times"]) == (
        "Clics de frustración", "Agregar al carrito", 2, 3,
    )  # fmt: skip
    # Las dos sesiones de V2 lo tuvieron: 2 de 2.
    assert rage["share"] == 1.0
    assert rage["by_version"] == "V0 0/2 · V2 2/2"
    assert rage["failed_tasks"] == 1
    assert rage["examples"] == "P03 (1:01), P04 (0:30)"
    assert rage["meaning"] and rage["check"]
    # Sin texto, el elemento se nombra por su selector; la sesión 9 no está elegida.
    assert (dead["element"], dead["people"], dead["by_version"]) == (
        "#zoom-badge", 2, "V0 1/2 · V2 1/2",
    )  # fmt: skip


def test_a_finding_also_seen_in_the_baseline_is_marked() -> None:
    found = findings.build_findings(incidents(), sessions(), task_results())

    assert found.set_index("element")["also_in_baseline"].to_dict() == {
        "Agregar al carrito": False,
        "#zoom-badge": True,
    }


@pytest.mark.parametrize(
    ("share", "people", "failed", "severity"),
    [
        (0.6, 6, 0, "Alta"),
        (0.1, 1, 1, "Alta"),
        (1.0, 1, 0, "Media"),  # una sola persona no es un patrón
        (0.3, 3, 0, "Media"),
        (0.1, 1, 0, "Baja"),
    ],
)
def test_the_proposed_severity_follows_reach_and_failed_tasks(
    share: float, people: int, failed: int, severity: str
) -> None:
    assert findings.propose_severity(share, people, failed) == severity


def test_no_incidents_means_no_findings() -> None:
    empty = incidents().iloc[0:0]

    assert findings.build_findings(empty, sessions(), task_results()).empty


def test_version_and_task_summaries() -> None:
    summary = findings.version_summary(sessions(), task_results()).set_index("version")
    tasks = findings.task_summary(task_results(), incidents(), sessions())

    assert summary.loc["V2", "success_rate"] == 0.75
    assert summary.loc["V0", "bui"] == 92.5
    assert summary.loc["V2", "sus"] == 57.5
    assert tasks["success_rate"].tolist() == [1.0, 0.75]
    assert tasks["median_s"].tolist() == [21.5, 34.0]
    assert tasks["main_incident"].tolist() == ["Clic sin respuesta (2)", "Clics de frustración (3)"]


def test_the_report_has_every_part_and_the_evaluator_text() -> None:
    found = findings.build_findings(incidents(), sessions(), task_results())
    found["recommendation"] = ["Mostrar un indicador de carga.", ""]
    report = findings.report_markdown(
        "Tienda", ["V0", "V2"], findings.version_summary(sessions(), task_results()),
        findings.task_summary(task_results(), incidents(), sessions()), found,
        conclusions="Corregir primero el botón.",
    )  # fmt: skip

    assert report.startswith("# Hallazgos de usabilidad · Tienda")
    assert "| V2 | 2 | 75 % | 2,0 | 60,0 | 57,5 |" in report
    assert "### 1. Clics de frustración en «Agregar al carrito» (/product/{id})" in report
    assert "- **Recomendación:** Mostrar un indicador de carga." in report
    assert "- **Recomendación:** Por definir." in report
    assert "posible falsa alarma" in report
    assert report.rstrip().endswith("Corregir primero el botón.")


def test_every_incident_type_of_the_contract_has_a_label_and_an_explanation() -> None:
    """Un tipo nuevo del contrato no puede aparecer en el panel sin nombre ni explicación."""
    types = set(contracts.enums()["incident_type"])

    assert set(findings.INCIDENT_ADVICE) == types
    assert set(charts.INCIDENT_LABELS) == types
    assert charts.incident_label("silent_failure") == "Fallo sin aviso"
