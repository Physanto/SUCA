"""Lectura del SUS: calificación, desglose por ítem y confiabilidad."""

import pandas as pd
import pytest

from dashboard import sus
from server.services import sus_score


@pytest.mark.parametrize(
    ("score", "label", "grade", "tone"),
    [
        (0, "Pobre", "F", "bad"),
        (50.8, "Pobre", "F", "bad"),
        (51.7, "Aceptable", "D", "ok"),
        (68, "Aceptable", "C", "ok"),
        (71.4, "Bueno", "C+", "good"),
        (80.8, "Bueno", "A", "good"),
        (85.5, "Excelente", "A+", "good"),
        (100, "Excelente", "A+", "good"),
    ],
)
def test_a_score_gets_its_label_grade_and_tone(
    score: float, label: str, grade: str, tone: str
) -> None:
    rating = sus.rate(score)
    assert (rating.label, rating.grade, rating.tone) == (label, grade, tone)


def test_the_comparison_with_the_average_says_which_side_it_is_on() -> None:
    assert "por encima" in sus.rate(80).versus_average
    assert "por debajo" in sus.rate(50).versus_average
    assert "Igual" in sus.rate(68.4).versus_average


@pytest.mark.parametrize("score", [-1, 100.5])
def test_a_score_outside_the_range_is_refused(score: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        sus.rate(score)


@pytest.mark.parametrize(
    "answers", [[5, 1, 5, 1, 5, 1, 5, 1, 5, 1], [3] * 10, [1, 5, 1, 5, 1, 5, 1, 5, 1, 5]]
)
def test_the_contributions_add_up_to_the_stored_score(answers: list[int]) -> None:
    assert sum(sus.contributions(answers)) * 2.5 == sus_score(answers)


@pytest.mark.parametrize("answers", [[3] * 9, [3] * 11, [0] + [3] * 9, [6] + [3] * 9])
def test_invalid_answers_are_refused(answers: list[int]) -> None:
    with pytest.raises(ValueError, match="10 answers"):
        sus.contributions(answers)


def test_the_breakdown_puts_the_worst_item_first() -> None:
    answers = pd.DataFrame(
        {"answers": [[5, 1, 5, 1, 5, 5, 5, 1, 5, 1], [5, 1, 5, 1, 5, 4, 5, 1, 5, 1]]}
    )
    table = sus.item_breakdown(answers)
    assert table.iloc[0]["item"] == 6  # «demasiada inconsistencia»
    assert table.iloc[0]["mean"] == pytest.approx(0.5)
    assert table.iloc[0]["share_low"] == 1.0
    assert len(table) == 10 and (table["mean"].iloc[1:] == 4).all()


def test_the_breakdown_skips_malformed_answers_and_handles_none() -> None:
    assert sus.item_breakdown(pd.DataFrame({"answers": []})).empty
    assert sus.item_breakdown(pd.DataFrame({"other": [1]})).empty
    mixed = pd.DataFrame({"answers": [[3] * 10, None, [9] * 10, "x"]})
    assert len(sus.item_breakdown(mixed)) == 10


@pytest.mark.parametrize(
    ("responses", "fragment"),
    [(0, "Nadie"), (3, "anécdota"), (8, "indicativo"), (12, ""), (40, "")],
)
def test_the_reliability_depends_on_how_many_answered(responses: int, fragment: str) -> None:
    text = sus.reliability(responses)
    assert (fragment in text) if fragment else text == ""


def test_summarize_ignores_missing_scores() -> None:
    summary = sus.summarize([80, None, 60, float("nan")])
    assert summary["count"] == 2 and summary["mean"] == 70
    assert summary["rating"].label == "Aceptable"
    empty = sus.summarize([None])
    assert empty["count"] == 0 and empty["rating"] is None and empty["warning"]
