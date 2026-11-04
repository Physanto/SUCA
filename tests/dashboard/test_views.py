"""Pruebas de los mapas de calor, las gráficas y la reproducción del panel, sin Streamlit."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from PIL import Image

from dashboard import charts, heatmap, replay
from dashboard.data import DashboardData


def events_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Eventos con las columnas de ``DashboardData.get_events``."""
    base = {"x": None, "y": None, "title": "", "task_id": None, "element": None, "data": None}
    return pd.DataFrame([{**base, **row} for row in rows])


@pytest.mark.parametrize(
    ("url", "screen"),
    [
        ("http://127.0.0.1:8767/product/101", "/product/{id}"),
        ("http://127.0.0.1:8767/products?sort=price_asc", "/products"),
        ("http://127.0.0.1:8767/product/104#resenas", "/product/{id}"),
        ("https://app.local/#/order/12/ok", "/order/{id}/ok"),
    ],
)
def test_screen_keys_follow_the_analysis_rule(url: str, screen: str) -> None:
    assert heatmap.screen_key(url) == screen


def test_points_are_placed_on_the_page_with_the_scroll_of_their_moment() -> None:
    """El scroll de la visita mueve los puntos; un cambio de pantalla vuelve arriba."""
    events = events_frame(
        [
            {"t": 0, "type": "screen_change", "url": "http://a/list"},
            {"t": 1, "type": "click", "x": 10, "y": 20, "url": "http://a/list"},
            {
                "t": 2,
                "type": "scroll",
                "url": "http://a/list",
                "data": {"scroll_x": 0, "scroll_y": 300},
            },
            {"t": 3, "type": "click", "x": 10, "y": 20, "url": "http://a/list"},
            {"t": 4, "type": "screen_change", "url": "http://a/product/7"},
            {"t": 5, "type": "click", "x": 30, "y": 40, "url": "http://a/product/7"},
        ]
    )
    gaze = pd.DataFrame(
        {
            "t": [3.5, 6.0],
            "x": [100.0, 200.0],
            "y": [50.0, 60.0],
            "scroll_x": [0.0, 0.0],
            "scroll_y": [300.0, 0.0],
        }
    )

    clicks = heatmap.points(events, gaze, "click")
    looks = heatmap.points(events, gaze, "gaze")

    assert clicks[["screen", "x", "y"]].values.tolist() == [
        ["/list", 10, 20],
        ["/list", 10, 320],
        ["/product/{id}", 30, 40],
    ]
    assert looks[["screen", "y"]].values.tolist() == [["/list", 350.0], ["/product/{id}", 60.0]]


def test_render_counts_what_falls_outside_the_capture() -> None:
    capture = Image.new("RGB", (2560, 1600), "white")  # devicePixelRatio 2

    drawn = heatmap.render([(100, 100), (500, 700), (500, 2000)], layer="click", background=capture)

    assert drawn.image.size == (1280, 800)
    assert (drawn.drawn, drawn.outside) == (2, 1)
    assert drawn.image.getpixel((100, 100)) != (255, 255, 255)
    assert drawn.image.getpixel((1200, 50)) == (255, 255, 255)


def test_render_without_capture_grows_to_the_lowest_point() -> None:
    drawn = heatmap.render([(50, 1500)], layer="gaze")

    assert drawn.image.size[1] > 1500 and drawn.drawn == 1


def test_charts_build_for_every_page(data: DashboardData) -> None:
    session = data.get_session(3)
    start = session["started_at"]
    results = data.get_task_results(1)
    index = data.get_usability_index(1)
    built = [
        charts.timeline(
            start,
            data.get_session_tasks(3),
            data.get_episodes(3),
            data.get_incidents(session_id=3),
            data.get_events(3),
        ),
        charts.face_signals(start, data.get_face(3)),
        charts.incidents_by_screen(data.get_incidents(study_id=1)),
        charts.time_by_screen(data.get_screen_summary(1)),
        charts.task_success(charts.task_summary(results)),
        charts.task_durations(results),
        charts.index_components(index),
        charts.bui_vs_sus(index),
    ]  # fmt: skip

    assert all(chart.to_dict() for chart in built)


def test_task_summary_compares_versions() -> None:
    results = pd.DataFrame(
        {
            "position": [1, 1, 1],
            "instruction": ["Buscar"] * 3,
            "version": ["V0", "V1", "V1"],
            "success": pd.array([True, True, False], dtype="boolean"),
            "duration_ms": [1000.0, 3000.0, 5000.0],
            "steps": [4, 6, 8],
            "deviation_step": pd.array([None, 2, 2], dtype="Int64"),
        }
    )

    summary = charts.task_summary(results).set_index("version")

    assert summary.loc["V1", "success_rate"] == 0.5
    assert summary.loc["V1", "median_duration_ms"] == 4000.0
    assert summary.loc["V1", "frequent_deviation"] == 2
    assert pd.isna(summary.loc["V0", "frequent_deviation"])


def test_correlation_needs_three_sessions() -> None:
    index = pd.DataFrame({"bui": [90, 60, 40], "sus_score": [85, 70, 30]})

    assert charts.correlation(index) == (1.0, 3)
    assert charts.correlation(index.head(2)) == (None, 2)


def test_gaze_at_clicks_measures_the_distance_to_each_click() -> None:
    events = events_frame(
        [
            {"t": 1000, "type": "click", "x": 100, "y": 100, "url": "http://a/"},
            {"t": 5000, "type": "click", "x": 400, "y": 400, "url": "http://a/"},
        ]
    )
    gaze = pd.DataFrame(
        {"t": [700.0, 900.0, 1050.0], "x": [130.0, 140.0, 500.0], "y": [140.0, 130.0, 500.0]}
    )

    distances = replay.gaze_at_clicks(events, gaze)
    summary = replay.agreement_summary(distances, clicks=2)

    # Solo el primer clic tiene mirada cerca en el tiempo; su mediana es (140, 140).
    assert distances["distance_px"].round(1).tolist() == [56.6]
    assert summary == {
        "clicks": 2,
        "with_gaze": 1,
        "median_px": pytest.approx(56.57, 0.01),
        "near_share": 1.0,
    }


def test_the_player_gets_the_session_with_relative_times(
    data: DashboardData, tmp_path: Path
) -> None:
    session = data.get_session(3)
    capture = tmp_path / "cart.png"
    Image.new("RGB", (1280, 800), "white").save(capture)
    captures = pd.DataFrame(
        {"url": ["https://shop.local/cart"], "t": [1.0], "absolute_path": [str(capture)]}
    )

    payload = replay.build_payload(
        session, data.get_events(3), data.get_gaze(3), data.get_session_tasks(3),
        data.get_incidents(session_id=3), captures,
    )  # fmt: skip
    html = replay.player_html(payload)

    assert payload["viewport"] == [1280, 800]
    assert payload["duration"] > 0 and payload["moves"] and payload["gaze"] and payload["tasks"]
    assert all(0 <= move[0] <= payload["duration"] for move in payload["moves"])
    assert list(payload["images"]) == ["/cart"]
    assert replay.PAYLOAD_MARK not in html and '"viewport":[1280,800]' in html


def replay_session() -> dict[str, Any]:
    """Sesión mínima para el reproductor: empieza en 1000 ms y dura 9 s."""
    return {"started_at": 1000.0, "ended_at": 10000.0, "screen_info": {}}


def test_a_window_keeps_what_was_on_screen_when_it_starts(tmp_path: Path) -> None:
    """Un tramo empieza con la pantalla, el scroll, el cursor y la captura que ya se veían."""
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (1280, 800), "white").save(image)
    events = events_frame(
        [
            {"t": 1000, "type": "screen_change", "url": "http://a/"},
            {"t": 1500, "type": "scroll", "url": "http://a/", "data": {"scroll_y": 300}},
            {"t": 1800, "type": "mousemove", "x": 5, "y": 6, "url": "http://a/"},
            {"t": 2000, "type": "click", "x": 5, "y": 6, "url": "http://a/"},
            {"t": 5000, "type": "click", "x": 50, "y": 60, "url": "http://a/"},
            {"t": 9000, "type": "click", "x": 9, "y": 9, "url": "http://a/"},
        ]
    )
    frames = pd.DataFrame({"t": [1200.0, 4500.0, 9500.0], "absolute_path": [str(image)] * 3})
    gaze = pd.DataFrame({"t": [4900.0], "x": [1.0], "y": [2.0]})
    no_rows = pd.DataFrame(columns=["t", "type", "screen"])

    payload = replay.build_payload(
        replay_session(), events, gaze, pd.DataFrame(columns=["t_start", "t_end"]), no_rows,
        pd.DataFrame(columns=["t", "url", "absolute_path"]), frames, window=(4000.0, 6000.0),
    )  # fmt: skip

    assert payload["duration"] == 2000
    assert [screen["t"] for screen in payload["screens"]] == [0]
    assert payload["scrolls"] == [[0, 0.0, 300.0]]
    assert payload["moves"] == [[0, 5, 6], [1000, 50, 60]]
    assert payload["clicks"] == [[1000, 50, 60]]
    assert payload["gaze"] == [[900, 1.0, 2.0]]
    assert payload["frames"] == [[0, 0], [500, 1]]
    assert len(payload["frame_images"]) == 2


def test_field_events_carry_their_box_and_what_was_typed() -> None:
    box = {"x": 10, "y": 20, "w": 100, "h": 30}
    rows = [
        ("focus_in", {}),
        ("field_change", {"length": 9, "deleted": 0, "field": "search", "text": "audifonos"}),
        ("field_change", {"length": 4, "deleted": 2}),
        ("field_change", {}),
        ("validation_error", {"error_type": "value_missing"}),
        ("focus_out", {}),
    ]
    events = events_frame(
        [
            {
                "t": 2000 + index,
                "type": kind,
                "url": "http://a/",
                "element": {"box": box},
                "data": data,
            }
            for index, (kind, data) in enumerate(rows)
        ]
    )
    no_rows = pd.DataFrame(columns=["t", "type", "screen"])

    payload = replay.build_payload(
        replay_session(), events, pd.DataFrame(columns=["t", "x", "y"]),
        pd.DataFrame(columns=["t_start", "t_end"]), no_rows,
        pd.DataFrame(columns=["t", "url", "absolute_path"]),
    )  # fmt: skip

    assert [(field["kind"], field["label"]) for field in payload["fields"]] == [
        ("focus", None),
        ("change", "«audifonos»"),
        ("change", "4 caracteres (borró 2)"),
        ("change", "cambió"),
        ("error", "error: value_missing"),
        ("blur", None),
    ]
    assert payload["fields"][0]["box"] == [10, 20, 100, 30]
    assert payload["frames"] == [] and payload["frame_images"] == []


def test_each_task_is_a_window_with_a_margin() -> None:
    tasks = pd.DataFrame(
        {
            "position": [2, 1],
            "instruction": ["B", "A"],
            "t_start": [9000, 3000],
            "t_end": [12000, 8000],
        }
    )

    assert replay.task_windows(tasks) == [
        ("Tarea 1: A", (1000.0, 10000.0)),
        ("Tarea 2: B", (7000.0, 14000.0)),
    ]
