"""Validación por persona de la comparación opcional con regresión logística."""

import numpy as np
import pandas as pd
import pytest

from analysis.ml.model import evaluate_models
from analysis.ml.windows import FACIAL_FEATURES, GAZE_FEATURES, INTERACTION_FEATURES


def test_each_prediction_is_for_a_person_absent_from_the_training_data() -> None:
    pytest.importorskip("sklearn", reason="optional ML dependencies: requirements-ml.txt")
    rng = np.random.default_rng(31)
    records = []
    for person in range(4):
        for window in range(20):
            label = window % 2
            row = {
                name: float(rng.normal(label, 0.2))
                for name in (*INTERACTION_FEATURES, *GAZE_FEATURES, *FACIAL_FEATURES)
            }
            records.append(
                {
                    **row,
                    "participant_id": f"P{person}",
                    "session_id": person,
                    "t_start": window * 2000.0,
                    "valid": True,
                    "label": label,
                }
            )
    report = evaluate_models(pd.DataFrame(records))
    assert len(report["scores"]) == 12
    assert len(report["predictions"]) == 240
    for fold in report["scores"]:
        assert fold["participant_id"] not in fold["train_participants"]
        assert len(fold["train_participants"]) == 3
        assert fold["balanced_accuracy"] > 0.9
