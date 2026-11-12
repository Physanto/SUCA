"""Pruebas estadísticas de la evaluación."""

import pandas as pd
import pytest

from scripts.evaluation import statistics

pytest.importorskip("scipy", reason="optional statistics dependencies: requirements-ml.txt")


def test_clearly_different_versions_are_told_apart() -> None:
    groups = {"V0": [90, 92, 95, 91, 93], "V1": [75, 78, 74, 77, 76], "V2": [60, 58, 62, 61, 59]}
    result = statistics.compare_groups(groups)
    assert result["anova"]["p"] < 0.001 and result["kruskal"]["p"] < 0.01
    assert result["anova"]["eta_squared"] > 0.9
    assert set(result["shapiro_p"]) == {"V0", "V1", "V2"}


def test_comparing_needs_three_values_per_group() -> None:
    with pytest.raises(ValueError, match="3 values"):
        statistics.compare_groups({"V0": [1, 2], "V1": [3, 4, 5]})


def test_the_trend_test_finds_a_decreasing_order_and_not_the_opposite() -> None:
    groups = [[90, 92, 95, 91], [75, 78, 74, 77], [60, 58, 62, 61]]
    down = statistics.jonckheere_terpstra(groups, permutations=2000)
    up = statistics.jonckheere_terpstra(groups, alternative="increasing", permutations=2000)
    # 4·4·3 = 48 pares, todos en el orden esperado.
    assert down["statistic"] == 48 and down["expected"] == 24
    assert down["p"] < 0.01 < up["p"]


def test_the_trend_test_counts_ties_as_half() -> None:
    assert statistics.jonckheere_terpstra([[5], [5]], permutations=10)["statistic"] == 0.5


def test_spearman_needs_three_pairs_and_ignores_missing_values() -> None:
    assert statistics.spearman([1, 2], [3, 4])["rho"] is None
    result = statistics.spearman([1, 2, 3, None, 5], [2, 4, 6, 8, 10])
    assert result["n"] == 4 and result["rho"] == pytest.approx(1.0)


def test_split_half_with_identical_halves_is_perfect() -> None:
    result = statistics.split_half([1, 2, 3, 4], [1, 2, 3, 4])
    assert result["r"] == pytest.approx(1.0) and result["spearman_brown"] == pytest.approx(1.0)


def test_discrepant_cases_are_the_sessions_whose_ranks_disagree() -> None:
    values = pd.DataFrame(
        {"session_id": [1, 2, 3, 4], "bui": [90, 80, 70, 20], "sus": [85, 75, 30, 90]}
    )
    # Rangos del IUC: 1, 0,75, 0,5, 0,25; del SUS: 0,75, 0,5, 0,25, 1.
    found = statistics.discrepant_cases(values, "bui", "sus", threshold=0.5)
    assert found["session_id"].tolist() == [4]
    assert found.iloc[0]["gap"] == pytest.approx(-0.75)  # SUS alto, IUC bajo.
    assert len(statistics.discrepant_cases(values, "bui", "sus", threshold=0.25)) == 4


def test_cohen_kappa_matches_a_hand_computed_case() -> None:
    # 20 casos: acuerdo observado 0,7; esperado 0,5·0,6 + 0,5·0,4 = 0,5; kappa 0,4.
    first = [1] * 10 + [0] * 10
    second = [1] * 8 + [0] * 2 + [1] * 4 + [0] * 6
    result = statistics.cohen_kappa(first, second)
    assert result["agreement"] == pytest.approx(0.7)
    assert result["kappa"] == pytest.approx(0.4)
    assert statistics.cohen_kappa([1, 1], [1, 1])["kappa"] is None
