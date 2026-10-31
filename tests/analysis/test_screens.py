"""Pruebas de identificación de pantallas y conservación de los datos capturados."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import columns, screens
from analysis.loader import (
    SESSION_FRAMES,
    SessionData,
    SqliteAnalysisRepository,
    validate_session_data,
)
from analysis.parameters import Parameters
from scripts.simulation import store
from scripts.simulation.builder import Click, Element, Screen, SessionBuilder
from shared import db


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Datos de la sesión guiada de la base pequeña."""
    return repository.load_session(1)


def with_pages(data: SessionData, pages: list[tuple[str, str]]) -> SessionData:
    """Sustituye los eventos por cambios de pantalla con URL y título conocidos."""
    events = columns.frame(
        "events",
        [
            {
                "t": data.session.started_at + index,
                "type": "screen_change",
                "url": url,
                "title": title,
                "screen": url,
            }
            for index, (url, title) in enumerate(pages)
        ],
    )
    return replace(data, events=events)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://shop.local/order/8812/items/42?view=all#details", "/order/{id}/items/{id}"),
        ("https://shop.local/search?q=audifonos&page=2", "/search"),
        ("https://shop.local/checkout/shipping#address", "/checkout/shipping"),
        ("https://shop.local/#/order/8812?source=menu", "/order/{id}"),
        ("https://shop.local/#!/order/42?source=menu", "/order/{id}"),
        ("https://shop.local/app#/order/42?source=menu", "/app#/order/{id}"),
        ("https://shop.local/v2/product/sku-42", "/v2/product/sku-42"),
        ("https://shop.local", "/"),
    ],
)
def test_normalizes_numeric_segments_queries_and_fragments(
    data: SessionData, params: Parameters, url: str, expected: str
) -> None:
    captured = with_pages(data, [(url, "Pantalla")])

    result = screens.assign_screens(captured, params)

    assert result.events["screen"].tolist() == [expected]
    assert result.events["url"].tolist() == [url]


def test_titles_do_not_split_different_ids_or_search_queries(
    data: SessionData, params: Parameters
) -> None:
    captured = with_pages(
        data,
        [
            ("https://shop.local/product/101", "Producto uno"),
            ("https://shop.local/product/202", "Producto dos"),
            ("https://shop.local/search?q=uno", "Resultados para uno"),
            ("https://shop.local/search?q=dos", "Resultados para dos"),
        ],
    )

    result = screens.assign_screens(captured, params)

    assert result.events["screen"].tolist() == [
        "/product/{id}",
        "/product/{id}",
        "/search",
        "/search",
    ]


def test_distinguishes_titles_at_the_same_url_without_changing_input(
    data: SessionData, params: Parameters
) -> None:
    url = "https://shop.local/dashboard"
    captured = with_pages(data, [(url, title) for title in ("Resumen", "Detalle", "Resumen", "")])
    captured.events.index = [8, 3, 8, 1]
    captured.events["capture_order"] = [0, 1, 2, 3]
    before = {name: getattr(captured, name).copy(deep=True) for name in SESSION_FRAMES}

    result = screens.assign_screens(captured, params)

    assert result is not captured
    assert result.session is captured.session
    assert result.events["screen"].tolist() == [
        "/dashboard | Resumen",
        "/dashboard | Detalle",
        "/dashboard | Resumen",
        "/dashboard",
    ]
    for name in SESSION_FRAMES:
        assert_frame_equal(getattr(captured, name), before[name], check_exact=True)
        if name != "events":
            assert_frame_equal(getattr(result, name), before[name], check_exact=True)
    assert_frame_equal(
        result.events.drop(columns="screen"),
        before["events"].drop(columns="screen"),
        check_exact=True,
    )
    assert_frame_equal(
        screens.assign_screens(result, params).events, result.events, check_exact=True
    )
    validate_session_data(result)


def test_empty_events_keep_their_columns_and_types(data: SessionData, params: Parameters) -> None:
    captured = replace(data, events=columns.empty("events"))

    result = screens.assign_screens(captured, params)

    assert_frame_equal(result.events, columns.empty("events"), check_exact=True)
    validate_session_data(result)


def test_builder_routes_remain_distinct_after_normalization(
    connection: sqlite3.Connection, params: Parameters
) -> None:
    first = Screen("https://shop.local/#/order/42", "Pedido", "/order/{id}")
    second = Screen("https://shop.local/#/checkout/payment", "Pago", "/checkout/payment")
    button = Element("button", "pay", "button", "Pagar", "#pay", (100, 200, 120, 40))
    recording = (
        SessionBuilder(study_id=1, camera=False)
        .on_screen(first)
        .do(Click(button, to=second))
        .build()
    )
    captured = store.load_session(connection, recording)

    result = screens.assign_screens(captured, params)

    changes = result.events[result.events["type"] == "screen_change"]
    assert changes["screen"].tolist() == [first.pattern, second.pattern]


def test_screens_match_every_visit_in_mock_ground_truth(mock: Any, params: Parameters) -> None:
    with closing(db.open_database(mock.path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        for session in mock.truth["sessions"]:
            captured = repository.load_session(session["session_id"])
            visits = [item for item in session["episodes"] if item["type"] == "screen"]

            result = screens.assign_screens(captured, params)

            assert visits
            for event in result.events.itertuples():
                expected = next(
                    visit["screen"]
                    for visit in visits
                    if visit["t_start"] <= event.t < visit["t_end"]
                )
                assert event.screen == expected, (session["key"], event.t, event.url)
