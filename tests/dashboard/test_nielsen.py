"""Relación orientativa entre los incidentes y las heurísticas de Nielsen."""

import pandas as pd

from dashboard import nielsen
from dashboard.charts import INCIDENT_LABELS
from shared import contracts


def test_every_incident_type_is_linked_to_valid_heuristics_with_a_reason() -> None:
    assert set(nielsen.LINKS) == set(contracts.enums()["incident_type"])
    for numbers, reason in nielsen.LINKS.values():
        assert numbers and set(numbers) <= set(nielsen.HEURISTICS)
        assert reason


def test_the_unobservable_heuristics_are_never_linked() -> None:
    linked = {number for numbers, _ in nielsen.LINKS.values() for number in numbers}
    assert not linked & set(nielsen.NOT_OBSERVABLE)
    assert set(nielsen.HEURISTICS) == set(range(1, 11))


def test_the_table_counts_signs_sessions_and_types_per_heuristic() -> None:
    incidents = pd.DataFrame(
        {
            "session_id": [1, 1, 2, 3],
            "type": ["form_error", "silent_failure", "form_error", "task_overtime"],
        }
    )
    table = nielsen.heuristic_table(incidents, INCIDENT_LABELS).set_index("number")
    # H9: form_error ×2 y silent_failure ×1, en 2 sesiones.
    assert table.loc[9, "signs"] == 3 and table.loc[9, "sessions"] == 2
    assert "Error de formulario (2)" in table.loc[9, "from_types"]
    assert table.loc[7, "signs"] == 1
    assert table.loc[8, "signs"] == 0 and not table.loc[8, "observable"]
    assert table.loc[1, "signs"] == 1  # silent_failure también apunta a H1


def test_the_table_has_the_ten_heuristics_even_without_incidents() -> None:
    table = nielsen.heuristic_table(pd.DataFrame(columns=["session_id", "type"]), {})
    assert table["number"].tolist() == list(range(1, 11)) and (table["signs"] == 0).all()


def test_the_caveat_says_it_is_not_a_heuristic_evaluation() -> None:
    assert "no una evaluación heurística" in nielsen.CAVEAT
