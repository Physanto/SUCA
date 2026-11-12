"""Pruebas de lo que acompaña a cada mapa de calor.

Cubren ``dashboard/heatmap_insights.py``, sus gráficas y la lectura de la
atribución de la mirada en ``dashboard/data.py``.
"""

from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dashboard import charts, heatmap_insights
from dashboard.data import DashboardData, open_data
from shared import db

VIEWPORT = (1200, 900)


def events(*rows: tuple[float, str, float | None, float | None, str, dict | None]) -> pd.DataFrame:
    """Eventos ``(t, tipo, x, y, url, elemento)`` con la forma de ``get_events``."""
    return pd.DataFrame(
        [
            {
                "t": t,
                "type": kind,
                "x": x,
                "y": y,
                "url": url,
                "title": "",
                "task_id": None,
                "element": element,
                "data": {},
            }
            for t, kind, x, y, url, element in rows
        ]
    )


def element(text: str | None, *, tag: str = "button", interactive: bool = True) -> dict:
    """Descriptor de elemento de un evento."""
    return {
        "tag": tag,
        "id": None,
        "role": None,
        "text": text,
        "selector": f"#{(text or tag).lower()}",
        "box": {"x": 0, "y": 0, "w": 10, "h": 10},
        "interactive": interactive,
    }


def test_the_zones_split_the_first_view_and_what_is_below() -> None:
    xy = np.array([[100, 100], [100, 120], [1100, 450], [600, 1500]])

    shares = heatmap_insights.zone_shares(xy, VIEWPORT).set_index(["row", "column"])

    assert len(shares) == 12
    assert shares.loc[("Arriba", "Izquierda"), "count"] == 2
    assert shares.loc[("Medio", "Derecha"), "count"] == 1
    assert shares.loc[("Debajo (con scroll)", "Centro"), "share"] == pytest.approx(0.25)
    assert shares["share"].sum() == pytest.approx(1.0)


def test_without_points_every_zone_is_empty() -> None:
    shares = heatmap_insights.zone_shares(np.empty((0, 2)), VIEWPORT)

    assert shares["share"].tolist() == [0.0] * 12


def test_elements_are_named_by_their_visible_text_or_tag_and_id() -> None:
    assert heatmap_insights.element_label(element("Ir a pagar")) == "“Ir a pagar” (button)"
    assert (
        heatmap_insights.element_label({**element(None, tag="input"), "id": "email"})
        == "input #email"
    )
    assert heatmap_insights.element_label(None) == "(sin elemento)"


def test_the_most_clicked_elements_of_a_screen_say_if_they_respond() -> None:
    url = "http://shop.local/product/7"
    frame = events(
        (1, "click", 10, 10, url, element("Comprar")),
        (2, "click", 10, 10, url, element("Comprar")),
        (3, "click", 50, 50, url, element("Foto", tag="img", interactive=False)),
        (4, "click", 50, 50, "http://shop.local/cart", element("Pagar")),
        (5, "mousemove", 50, 50, url, None),
    )

    top = heatmap_insights.top_clicked(frame, "/product/{id}")

    assert top.values.tolist() == [["“Comprar” (button)", 2, True], ["“Foto” (img)", 1, False]]


def test_the_cursor_distance_does_not_join_two_visits() -> None:
    url = "http://shop.local/"
    frame = events(
        (1, "screen_change", None, None, url, None),
        (2, "mousemove", 0, 0, url, None),
        (3, "mousemove", 300, 400, url, None),
        (4, "screen_change", None, None, url, None),
        (5, "mousemove", 1000, 0, url, None),
        (6, "mousemove", 1000, 100, url, None),
    )

    assert heatmap_insights.cursor_distance_px(frame, "/") == pytest.approx(600)


def test_the_gaze_time_splits_each_fixation_by_its_probabilities() -> None:
    fixations = pd.DataFrame(
        {
            "fixation": [0, 1, 2],
            "t_start": [0.0, 1000.0, 5000.0],
            "t_end": [400.0, 1200.0, 5400.0],
            "screen": ["http://shop.local/", "http://shop.local/", "http://shop.local/cart"],
            "element_selector": ["#search", "#title", "#pay"],
        }
    )
    attribution = pd.DataFrame(
        {
            "fixation": [0, 0, 0, 1, 1, 2],
            "selector": ["#search", "#title", None, "#title", None, "#pay"],
            "tag": ["input", "h1", None, "h1", None, "button"],
            "interactive": [True, False, None, False, None, True],
            "p_gaze": [0.75, 0.2, 0.05, 0.5, 0.5, 1.0],
            "p_attention": [0.9, 0.1, 0.0, 0.5, 0.5, 1.0],
        }
    )

    dwell = heatmap_insights.gaze_dwell(
        fixations, attribution, "/", {"#search": "“Buscar” (input)"}
    ).set_index("label")

    assert dwell.loc["“Buscar” (input)", "seconds"] == pytest.approx(0.3)
    assert dwell.loc["#title", "seconds"] == pytest.approx(0.08 + 0.1)
    assert dwell.loc[heatmap_insights.UNASSIGNED_LABEL, "seconds"] == pytest.approx(0.02 + 0.1)
    assert dwell.index[-1] == heatmap_insights.UNASSIGNED_LABEL
    assert "#pay" not in " ".join(dwell.index)


def test_elements_without_text_get_distinct_names() -> None:
    fixations = pd.DataFrame(
        {
            "fixation": [0, 1],
            "t_start": [0.0, 1000.0],
            "t_end": [300.0, 1200.0],
            "screen": ["http://shop.local/"] * 2,
            "element_selector": ["main > div.card > h3 > a", "main > div.other > h3 > a"],
        }
    )
    attribution = pd.DataFrame(
        {
            "fixation": [0, 1],
            "selector": ["main > div.card > h3 > a", "main > div.other > h3 > a"],
            "tag": ["a", "a"],
            "interactive": [True, True],
            "p_gaze": [1.0, 1.0],
            "p_attention": [1.0, 1.0],
        }
    )

    labels = heatmap_insights.gaze_dwell(fixations, attribution, "/")["label"].tolist()

    assert labels == ["h3 › a", "h3 › a (2)"]


def test_the_gaze_states_are_shares_of_the_time_in_spanish() -> None:
    states = pd.DataFrame(
        {"t": range(4), "state": ["on_screen", "on_screen", "off_screen", "blink"]}
    )

    shares = heatmap_insights.gaze_state_shares(states).set_index("state")["share"]

    assert shares["Mira la pantalla"] == pytest.approx(0.5)
    assert shares["Fuera de la pantalla"] == pytest.approx(0.25)


def test_the_charts_build_with_and_without_unassigned_time() -> None:
    zones = heatmap_insights.zone_shares(np.array([[10, 10]]), VIEWPORT)
    top = pd.DataFrame(
        {"label": ["A", "Sin asignar"], "seconds": [1.0, 2.0], "interactive": [True, None]}
    )
    states = pd.DataFrame({"state": ["Mira la pantalla"], "share": [1.0]})

    for chart in (
        charts.zone_grid(zones, "clics"),
        charts.top_elements(top, "seconds", "Segundos", fmt=".1f"),
        charts.gaze_states(states),
    ):
        assert chart.to_dict()


def test_the_data_reads_the_attributed_fixations(tmp_path: Path) -> None:
    path = tmp_path / "suca.db"
    with closing(db.connect(path, create=True)) as connection:
        db.create_schema(connection)
        connection.execute("INSERT INTO study (id, name, system_under_test) VALUES (1, 'E', 'App')")
        connection.execute("INSERT INTO participant (id) VALUES ('P1')")
        connection.execute(
            "INSERT INTO session (id, study_id, participant_id, version, mode, started_at,"
            " screen_info) VALUES (1, 1, 'P1', 'V0', 'free', 0, '{}')"
        )
        connection.execute(
            "INSERT INTO gaze_fixation (session_id, fixation, t_start, t_end, x, y, scroll_x,"
            " scroll_y, screen, sigma_px, element_selector, element_p, resolved_selector,"
            " resolved_p, ambiguous, unassigned_p, attention_selector, attention_p, long_stare)"
            " VALUES (1, 0, 0, 300, 10, 10, 0, 0, 'http://a/', 50, '#a', 0.9, '#a', 0.9, 0,"
            " 0.05, '#a', 0.95, 1)"
        )
        connection.execute(
            "INSERT INTO gaze_attribution VALUES (1, 0, '#a', 'a', 1, 0.9, 0.95),"
            " (1, 0, NULL, NULL, NULL, 0.05, 0.02)"
        )
        connection.execute(
            "INSERT INTO gaze_sample (session_id, t, x, y, scroll_x, scroll_y, valid, state,"
            " confidence) VALUES (1, 5, NULL, NULL, 0, 0, 0, 'off_screen', 1)"
        )
        connection.commit()
    with open_data(path) as data:
        assert isinstance(data, DashboardData)
        fixations = data.get_gaze_fixations(1)
        attribution = data.get_gaze_attribution(1)
        states = data.get_gaze_states(1)
        empty = data.get_gaze_fixations(2)

    assert fixations[["fixation", "element_selector", "long_stare"]].values.tolist() == [
        [0, "#a", True]
    ]
    assert attribution["selector"].isna().sum() == 1
    assert states["state"].tolist() == ["off_screen"]
    assert empty.empty and "unassigned_p" in empty.columns
