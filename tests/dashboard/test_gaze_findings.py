"""La evidencia anterior al incidente no incorpora interacción ni eventos futuros."""

import pandas as pd
import pytest

from dashboard.gaze_findings import before_incidents
from tests.dashboard.test_views import events_frame


def test_next_element_uses_only_prior_gaze_and_each_reference_separately() -> None:
    first = {"selector": "#first", "id": "first", "interactive": True,
             "text": "Primero", "role": "button"}
    second = {**first, "selector": "#next", "id": "next", "text": "Siguiente"}
    steps = [{"t": t, "type": "click", "screen": {"url": "http://a/home", "title": ""},
              "element": element} for t, element in [(0, first), (1, second)]]
    events = events_frame([
        {"t": 1000, "type": "click", "url": "http://a/home", "element": first, "task_id": 1},
        {"t": 9000, "type": "click", "url": "http://a/home", "element": second, "task_id": 1},
    ])
    references = pd.DataFrame([
        {"reference_id": rid, "task_id": 1, "status": "confirmed", "steps": steps}
        for rid in [1, 2]
    ])
    fixations = pd.DataFrame([
        {"fixation": i, "t_start": start, "t_end": end, "screen": "http://a/home"}
        for i, start, end in [(0, 2000, 2500), (1, 4000, 4500), (2, 5900, 6200), (3, 6500, 6800)]
    ])
    candidates = pd.DataFrame([
        {"fixation": i, "selector": "#next", "p_gaze": .2, "p_attention": .99}
        for i in range(4)
    ])
    incidents = pd.DataFrame([{"t": 6000, "type": "dead_click", "task_id": 1}])
    tasks = pd.DataFrame([{"task_id": 1, "t_start": 500, "t_end": 10000}])
    report = before_incidents(incidents, events, references, fixations, candidates, tasks)
    assert report["reference_id"].tolist() == [1, 2]
    assert report["selector"].tolist() == ["#next", "#next"]
    assert report["p_seen"].tolist() == pytest.approx([.36, .36])
    assert report["fixations"].tolist() == [2, 2]


def test_missing_attribution_does_not_imply_a_zero_probability() -> None:
    incidents = pd.DataFrame([{"t": 6000, "type": "dead_click", "task_id": 1}])
    report = before_incidents(
        incidents, events_frame([]),
        pd.DataFrame(columns=["task_id", "status"]), pd.DataFrame(), pd.DataFrame(),
        pd.DataFrame(),
    )
    assert report.iloc[0]["p_seen"] is None
    assert report.iloc[0]["reason"] == "Sin referencia confirmada"
