"""Rasgos faciales con línea base marcada, pose extrema y huecos conocidos."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from analysis import columns
from analysis.loader import SessionData, SqliteAnalysisRepository
from analysis.ml.facial import MOVEMENTS, FacialSettings, facial_windows, neutral_baseline
from analysis.ml.windows import build_windows
from dashboard.facial_insights import incident_comparison


def face_samples() -> pd.DataFrame:
    """Diez segundos neutros y cuatro con descenso de cejas y un parpadeo."""
    keys = {key for group in MOVEMENTS.values() for key in group}
    rows = []
    for t in range(1000, 15000, 100):
        values = dict.fromkeys(keys, 0.1)
        if t >= 11000:
            values.update(brow_down_left=0.3, brow_down_right=0.3)
        if t == 12000:
            values.update(eye_blink_left=0.8, eye_blink_right=0.8)
        rows.append(
            {
                "t": float(t),
                "face_detected": True,
                "head_yaw": 0.0,
                "head_pitch": 0.0,
                "values": values,
            }
        )
    return pd.DataFrame(rows)


def targets() -> pd.DataFrame:
    """Tramo neutro explícito, sin reconstruirlo de otras señales."""
    return pd.DataFrame(
        [
            {
                "t": 1000.0,
                "t_end": 11000.0,
                "phase": "neutral_baseline",
                "calibration_type": "initial",
            }
        ]
    )


def test_movements_are_relative_to_the_person_and_blinks_count_closures() -> None:
    face = face_samples()
    baseline = neutral_baseline(face, targets())
    windows = facial_windows(face, baseline, 1000, 15000)
    assert baseline.samples == 100
    assert windows["valid"].all()
    assert windows["brow_down_delta"].tolist() == pytest.approx([0.2, 0.2])
    assert windows["mouth_press_delta"].tolist() == pytest.approx([0, 0])
    assert windows["blink_rate_per_min"].tolist() == [30, 0]


def test_extreme_pose_and_long_gaps_invalidate_windows_instead_of_becoming_zero() -> None:
    face = face_samples()
    baseline = neutral_baseline(face, targets())
    face.loc[face["t"].between(11000, 11900), "head_yaw"] = 40
    windows = facial_windows(face, baseline, 11000, 15000)
    assert not windows.iloc[0]["valid"]
    assert pd.isna(windows.iloc[0]["brow_down_delta"])
    assert windows.iloc[1]["valid"]
    gapped = face[~face["t"].between(13300, 13800)]
    assert not facial_windows(gapped, baseline, 13000, 15000).iloc[0]["valid"]


def test_old_sessions_without_a_marked_baseline_are_rejected() -> None:
    with pytest.raises(ValueError, match="no usable marked neutral baseline"):
        neutral_baseline(face_samples(), targets().assign(phase="validation"))


def test_a_long_baseline_gap_is_not_hidden_by_its_number_of_samples() -> None:
    face = face_samples()
    with pytest.raises(ValueError, match="no usable marked neutral baseline"):
        neutral_baseline(face[~face["t"].between(3000, 4000)], targets())


def test_labels_are_not_features_and_calibration_windows_are_invalid(
    repository: SqliteAnalysisRepository,
) -> None:
    data: SessionData = repository.load_session(1)
    session = replace(data.session, started_at=1000, ended_at=15000)
    gaze = columns.frame(
        "gaze",
        [
            {
                "t": float(t),
                "x": 300.0,
                "y": 100.0,
                "scroll_x": 0.0,
                "scroll_y": 0.0,
                "element_selector": None,
                "zone": None,
                "valid": True,
            }
            for t in range(11000, 15000, 100)
        ],
    )
    data = replace(
        data,
        session=session,
        face=face_samples(),
        events=columns.empty("events"),
        gaze=gaze,
        tasks=columns.empty("tasks"),
    )
    fixation = columns.empty("gaze_fixation")
    incidents = columns.frame("incident", [{"t": 12000.0, "type": "dead_click"}])
    first = build_windows(data, targets(), fixation, incidents, columns.empty("task_result"))
    second = build_windows(
        data, targets(), fixation, columns.empty("incident"), columns.empty("task_result")
    )
    assert first["label"].tolist() == [1, 0]
    assert second["label"].tolist() == [0, 0]
    pd.testing.assert_frame_equal(first.drop(columns="label"), second.drop(columns="label"))
    extra = pd.concat([targets(), targets().assign(t=13000, t_end=13500, phase="drift_check")])
    assert not build_windows(data, extra, fixation, incidents, columns.empty("task_result")).iloc[
        1
    ]["valid"]


def test_incident_comparison_uses_movement_names_and_flags_missing_controls() -> None:
    table = incident_comparison(
        face_samples(), targets(), pd.DataFrame({"t": [12000]}), 1000, 15000
    )
    assert "Descenso de cejas" in table["Movimiento"].tolist()
    assert table["Ventanas de control"].eq(0).all()
    assert table["Control"].isna().all()


@pytest.mark.parametrize(
    "kwargs",
    [{"window_ms": 500}, {"max_pose_deg": np.nan}, {"min_valid_share": 2}, {"blink_threshold": 1}],
)
def test_invalid_facial_settings_fail_early(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        FacialSettings(**kwargs)
