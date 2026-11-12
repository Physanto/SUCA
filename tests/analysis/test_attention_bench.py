"""Banco de atribución con verdad simulada, límites temporales y persistencia real."""

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from analysis import columns
from analysis.gaze.attention_bench import AttentionScript, evaluate, render, report_to_json
from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import load_parameters
from scripts import attention_bench
from tests.analysis.test_gaze_attention import element, interactions, layouts, run, samples


def script(*targets: tuple[str, str | None]) -> AttentionScript:
    """Guion corto con el mismo reloj que la página."""
    return AttentionScript.from_dict(
        {
            "version": 1,
            "start_selector": "#start",
            "step_ms": 3000,
            "settle_ms": 500,
            "targets": [{"kind": kind, "selector": selector} for kind, selector in targets],
        }
    )


def states(*rows: tuple[float, str]) -> pd.DataFrame:
    """Muestras del monitor incluidas las que no producen fijación."""
    return pd.DataFrame(rows, columns=["t", "state"])


def test_scores_elements_empty_space_and_keyboard_without_interaction_bias() -> None:
    params = load_parameters().attention
    screen = layouts((0, [element("#title", 100, 100, 400, 60, tag="h1")]))
    result = run(params, samples((600, 900, 300, 130), (3600, 3900, 1100, 650)), screen)
    report = evaluate(
        interactions((0, "click", "#start")),
        result.fixations,
        result.candidates,
        states((600, "on_screen"), (3600, "on_screen"), (6600, "off_screen")),
        screen,
        script(("element", "#title"), ("empty", None), ("keyboard", None)),
    )
    assert report.summary["scored_fixations"] == 2
    assert report.summary["p_gaze_accuracy"] == 1
    assert report.summary["p_attention_accuracy"] == 1
    assert report.summary["baseline_accuracy"] == 1
    assert report.summary["keyboard_off_screen_share"] == 1
    assert report.summary["empty_unassigned_p"] > report.summary["element_unassigned_p"]
    reliability = report.by_probability.query("fixations > 0")
    assert set(reliability["channel"]) == {"p_gaze", "p_attention"}
    assert reliability["accuracy"].eq(1).all()
    assert "p_attention es referencia" in render(report)
    json.dumps(report_to_json(report), allow_nan=False)


def test_drops_saccades_and_fixations_crossing_a_target_boundary() -> None:
    screen = layouts((0, [element("#a", 100, 100, 400, 60)]))
    result = run(
        load_parameters().attention,
        samples(
            (100, 400, 300, 130),
            (500, 700, 300, 130),
            (2900, 3100, 300, 130),
            (3500, 3700, 300, 130),
        ),
        screen,
    )
    report = evaluate(
        interactions((0, "click", "#start")),
        result.fixations,
        result.candidates,
        states(),
        screen,
        script(("element", "#a"), ("element", "#a")),
    )
    assert report.fixations["fixation"].tolist() == [1, 3]


def test_resolved_accuracy_accepts_the_expected_elements_ancestor() -> None:
    card = [
        element("#card", 100, 300, 300, 200, tag="article"),
        element("#more", 120, 460, 60, 16, parent=0),
        element("#buy", 190, 460, 60, 16, parent=0),
    ]
    screen = layouts((0, card))
    result = run(load_parameters().attention, samples((600, 900, 185, 468)), screen)
    report = evaluate(
        interactions((0, "click", "#start")),
        result.fixations,
        result.candidates,
        states(),
        screen,
        script(("element", "#buy")),
    )
    assert result.fixations.iloc[0]["resolved_selector"] == "#card"
    assert report.summary["resolved_accuracy"] == 1
    assert report.summary["element_accuracy"] == 0


def test_missing_capture_is_reported_as_missing_instead_of_a_wrong_prediction() -> None:
    report = evaluate(
        interactions((0, "click", "#start")),
        columns.empty("gaze_fixation"),
        columns.empty("gaze_attribution"),
        states(),
        layouts(),
        script(("element", "#a"), ("keyboard", None)),
    )
    data = report_to_json(report)
    assert data["summary"]["p_gaze_accuracy"] is None
    assert data["summary"]["keyboard_off_screen_share"] is None
    assert data["summary"]["targets_with_samples"] == 0
    assert len(data["by_target"]) == 2
    json.dumps(data, allow_nan=False)


@pytest.mark.parametrize(
    "events,message",
    [
        (interactions(), "no script start"),
        (interactions((0, "click", "#start"), (9000, "click", "#start")), "multiple start"),
    ],
)
def test_requires_an_unambiguous_start_click(events: pd.DataFrame, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate(
            events,
            columns.empty("gaze_fixation"),
            columns.empty("gaze_attribution"),
            states(),
            layouts(),
            script(("element", "#a")),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"step_ms": 0},
        {"settle_ms": 3000},
        {"step_ms": float("nan")},
        {"targets": []},
        {"targets": [{"kind": "keyboard", "selector": "#a"}]},
    ],
)
def test_rejects_invalid_scripts(change: dict) -> None:
    document = {
        "version": 1,
        "start_selector": "#start",
        "step_ms": 3000,
        "settle_ms": 500,
        "targets": [{"kind": "element", "selector": "#a"}],
    }
    with pytest.raises(ValueError):
        AttentionScript.from_dict({**document, **change})


def test_cli_reads_saved_attribution_and_writes_strict_json(
    connection: sqlite3.Connection,
    repository: SqliteAnalysisRepository,
    analysis_db: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    screen = layouts((0, [element("#title", 100, 100, 400, 60)]))
    result = run(load_parameters().attention, samples((600, 900, 300, 130)), screen)
    repository.save_gaze_attention(1, result.fixations, result.candidates)
    connection.execute(
        "INSERT INTO event (session_id,t,type,element,screen) VALUES (1,0,'click',?,?)",
        (json.dumps({"selector": "#start"}), json.dumps({"url": "http://app.local/home"})),
    )
    connection.commit()
    path = tmp_path / "script.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "start_selector": "#start",
                "step_ms": 3000,
                "settle_ms": 500,
                "targets": [{"kind": "element", "selector": "#title"}],
            }
        )
    )
    output = tmp_path / "report.json"
    assert (
        attention_bench.main(
            [
                "--session",
                "1",
                "--db",
                str(analysis_db),
                "--script",
                str(path),
                "--json",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["summary"]["scored_fixations"] == 1
    assert "Atribución frente" in capsys.readouterr().out


def test_baseline_translates_scrolled_boxes_and_keeps_fixed_ones() -> None:
    screen = layouts(
        (
            0,
            [
                element("#below", 100, 900, 400, 60),
                element("#fixed", 100, 600, 400, 60, fixed=True),
            ],
        )
    )
    result = run(
        load_parameters().attention,
        samples((600, 900, 300, 430), (3600, 3900, 300, 630), scroll_y=500),
        screen,
    )
    report = evaluate(
        interactions((0, "click", "#start")),
        result.fixations,
        result.candidates,
        states(),
        screen,
        script(("element", "#below"), ("element", "#fixed")),
    )
    assert report.summary["baseline_accuracy"] == 1


def test_reliability_bins_keep_boundaries_and_report_overconfidence() -> None:
    screen = layouts((0, [element("#title", 100, 100, 400, 60)]))
    result = run(
        load_parameters().attention,
        samples(*[(k * 3000 + 600, k * 3000 + 900, 300, 130) for k in range(5)]),
        screen,
    )
    rows = []
    for k, probability in enumerate([0.4, 0.6, 0.8, 0.95, 1.0]):
        for selector, p in [
            ("#title", probability),
            ("#other", (1 - probability) * 0.6),
            (None, (1 - probability) * 0.4),
        ]:
            rows.append({"fixation": k, "selector": selector, "p_gaze": p, "p_attention": p})
    report = evaluate(
        interactions((0, "click", "#start")),
        result.fixations,
        pd.DataFrame(rows),
        states(),
        screen,
        script(*[("element", "#title")] * 4, ("element", "#wrong")),
    )
    bins = report.by_probability.query("channel == 'p_gaze' and fixations > 0")
    assert bins["low"].tolist() == [0.4, 0.6, 0.8, 0.95]
    last = bins.iloc[-1]
    assert last["mean_probability"] == pytest.approx(0.975)
    assert last["accuracy"] == 0.5
