"""Pruebas de la atribución de la mirada a los elementos de la pantalla.

Cubren los casos con verdad conocida (título frente a buscador, mirada entre
los dos, el clic que desempata solo en la atención estimada, el vacío, dos
enlaces pequeños dentro de una tarjeta), la secuencia, el scroll, la mirada
fija prolongada, los registros anteriores a la versión 1.6.0 del contrato, la
calibración de las probabilidades con una sesión simulada, el guardado y la
integración en el orquestador.
"""

import json
import math
import sqlite3
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis import columns
from analysis.gaze import GazeSettings
from analysis.gaze.attention import (
    GazeAttention,
    attribute,
    error_sigma_px,
    probability_seen,
)
from analysis.loader import GazeInputs, SqliteAnalysisRepository
from analysis.parameters import AttentionParams, Parameters, load_parameters
from analysis.run import analyze_session
from server.ingestion import handler_for
from server.repositories import SqliteRepository
from shared.config import ROOT_DIR

URL = "http://app.local/home"
SETTINGS = GazeSettings(
    css_px_per_cm=40.0,
    viewing_distance_cm=60.0,
    blink_threshold=0.45,
    params=load_parameters().gaze,
)
PX_PER_DEG = 40.0 * 60.0 * math.tan(math.radians(1))


@pytest.fixture
def attention() -> AttentionParams:
    """Parámetros por defecto de la atribución."""
    return load_parameters().attention


def element(
    selector: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    tag: str = "div",
    interactive: bool = False,
    parent: int | None = None,
    fixed: bool = False,
) -> dict:
    """Elemento de una disposición con la forma de ``layout.schema.json``."""
    return {
        "selector": selector,
        "tag": tag,
        "role": None,
        "box": {"x": x, "y": y, "w": w, "h": h},
        "fixed": fixed,
        "interactive": interactive,
        "parent": parent,
    }


def layouts(
    *records: tuple[float, list[dict]], url: str = URL, scroll_y: float = 0
) -> pd.DataFrame:
    """Disposiciones de una sesión: ``(t, elementos)`` por registro."""
    return columns.frame(
        "layouts",
        [
            {
                "t": t,
                "screen": {"url": url, "title": "Inicio"},
                "viewport_width": 1200.0,
                "viewport_height": 800.0,
                "scroll_x": 0.0,
                "scroll_y": scroll_y,
                "regions": [],
                "elements": items,
                "truncated": False,
            }
            for t, items in records
        ],
    )


def samples(*fixations: tuple[float, float, float, float], scroll_y: float = 0) -> pd.DataFrame:
    """Mirada reprocesada con una fijación por ``(t_start, t_end, x, y)``, a 30 Hz."""
    rows = []
    for number, (start, end, x, y) in enumerate(fixations):
        for t in np.arange(start, end + 1, 33.0):
            rows.append(
                {
                    "t": float(min(t, end)),
                    "x": x,
                    "y": y,
                    "scroll_x": 0.0,
                    "scroll_y": scroll_y,
                    "state": "on_screen",
                    "confidence": 1.0,
                    "valid": True,
                    "zone": None,
                    "element_selector": None,
                    "fixation": number,
                }
            )
    return columns.frame("gaze_refined", rows)


def interactions(*events: tuple[float, str, str | None]) -> pd.DataFrame:
    """Eventos ``(t, tipo, selector)``."""
    return columns.frame(
        "gaze_interactions", [{"t": t, "type": kind, "selector": s} for t, kind, s in events]
    )


def p_of(result: GazeAttention, fixation: int, selector: str | None, column: str) -> float:
    """Probabilidad de un candidato en una fijación (0 si no se guardó)."""
    rows = result.candidates[result.candidates["fixation"] == fixation]
    if selector is None:
        match = rows[rows["selector"].isna()]
    else:
        match = rows[rows["selector"] == selector]
    return float(match[column].sum())


TITLE_AND_SEARCH = [
    element("#title", 100, 100, 400, 60, tag="h1"),
    element("#search", 520, 100, 400, 60, tag="input", interactive=True),
]
"""Un título y, a 20 px, el buscador: el caso "¿miraba el título o la búsqueda?"."""


def run(
    attention: AttentionParams,
    gaze: pd.DataFrame,
    screen: pd.DataFrame,
    events: pd.DataFrame | None = None,
    error_deg: float = 1.0,
) -> GazeAttention:
    """Atribuye con los ajustes de prueba."""
    return attribute(
        gaze,
        screen,
        interactions() if events is None else events,
        error_deg,
        SETTINGS,
        attention,
    )


def test_a_fixation_on_the_title_is_the_title(attention: AttentionParams) -> None:
    result = run(attention, samples((1000, 1300, 300, 130)), layouts((0, TITLE_AND_SEARCH)))

    row = result.fixations.iloc[0]
    assert row["element_selector"] == "#title"
    assert row["element_p"] > 0.9
    assert row["resolved_selector"] == "#title"
    assert not row["ambiguous"]
    assert row["screen"] == URL


def test_between_title_and_search_both_are_possible(attention: AttentionParams) -> None:
    result = run(attention, samples((1000, 1300, 510, 130)), layouts((0, TITLE_AND_SEARCH)))

    title = p_of(result, 0, "#title", "p_gaze")
    search = p_of(result, 0, "#search", "p_gaze")
    assert abs(title - search) < 0.02
    assert 0.35 < title < 0.55
    # Nadie se da por mirado: no hay ancestro que reúna a los dos.
    assert result.fixations.iloc[0]["resolved_selector"] is None


def test_a_click_on_search_tips_the_attention_but_not_the_gaze(
    attention: AttentionParams,
) -> None:
    gaze = samples((1000, 1300, 510, 130))
    screen = layouts((0, TITLE_AND_SEARCH))
    alone = run(attention, gaze, screen)

    clicked = run(attention, gaze, screen, interactions((1500, "click", "#search")))

    # La mirada sola no sabe nada del clic: P5 no se infla.
    assert p_of(clicked, 0, "#search", "p_gaze") == pytest.approx(
        p_of(alone, 0, "#search", "p_gaze")
    )
    # La atención estimada lo da por casi seguro, sin llegar a 1.
    assert 0.8 < p_of(clicked, 0, "#search", "p_attention") < 0.95
    assert clicked.fixations.iloc[0]["attention_selector"] == "#search"


def test_a_click_far_from_the_gaze_does_not_drag_it(attention: AttentionParams) -> None:
    result = run(
        attention,
        samples((1000, 1300, 300, 130)),
        layouts((0, TITLE_AND_SEARCH)),
        interactions((1500, "click", "#search")),
    )

    assert result.fixations.iloc[0]["attention_selector"] == "#title"


def test_a_click_long_after_the_fixation_does_not_count(attention: AttentionParams) -> None:
    gaze = samples((1000, 1300, 510, 130))
    screen = layouts((0, TITLE_AND_SEARCH))

    result = run(attention, gaze, screen, interactions((4000, "click", "#search")))

    assert p_of(result, 0, "#search", "p_attention") == pytest.approx(
        p_of(result, 0, "#search", "p_gaze")
    )


def test_looking_at_empty_space_is_unassigned(attention: AttentionParams) -> None:
    result = run(attention, samples((1000, 1300, 1000, 650)), layouts((0, TITLE_AND_SEARCH)))

    row = result.fixations.iloc[0]
    assert row["unassigned_p"] > 0.95
    assert row["element_selector"] is None
    assert p_of(result, 0, None, "p_gaze") == pytest.approx(row["unassigned_p"])


def test_two_small_links_resolve_to_the_card_that_holds_them(attention: AttentionParams) -> None:
    card = [
        element("#card", 100, 300, 300, 200, tag="article"),
        element("#more", 120, 460, 60, 16, tag="a", interactive=True, parent=0),
        element("#buy", 190, 460, 60, 16, tag="a", interactive=True, parent=0),
    ]

    result = run(attention, samples((1000, 1300, 185, 468)), layouts((0, card)))

    row = result.fixations.iloc[0]
    assert row["element_p"] < attention.confident_probability
    assert row["resolved_selector"] == "#card"
    assert row["ambiguous"]
    assert row["resolved_p"] >= attention.confident_probability


def test_the_sequence_helps_an_ambiguous_fixation(attention: AttentionParams) -> None:
    screen = layouts((0, TITLE_AND_SEARCH))
    middle = (1600, 1900, 510, 130)
    on_title = [(1000, 1300, 300, 130), (2200, 2500, 300, 130)]
    isolated = run(attention, samples(middle), screen)

    linked = run(attention, samples(on_title[0], middle, on_title[1]), screen)

    assert p_of(linked, 1, "#title", "p_gaze") > p_of(isolated, 0, "#title", "p_gaze") + 0.1


@pytest.mark.parametrize("cut", ["gap", "screen"])
def test_a_long_gap_or_a_new_screen_cuts_the_sequence(attention: AttentionParams, cut: str) -> None:
    middle_start = 1600 if cut == "screen" else 1300 + attention.sequence_max_gap_ms + 100
    gaze = samples((1000, 1300, 300, 130), (middle_start, middle_start + 300, 510, 130))
    screen = layouts((0, TITLE_AND_SEARCH))
    if cut == "screen":
        other = layouts((middle_start - 50, TITLE_AND_SEARCH), url="http://app.local/other")
        screen = pd.concat([screen, other], ignore_index=True)
    isolated = run(attention, samples((1000, 1300, 510, 130)), layouts((0, TITLE_AND_SEARCH)))

    result = run(attention, gaze, screen)

    assert p_of(result, 1, "#title", "p_gaze") == pytest.approx(
        p_of(isolated, 0, "#title", "p_gaze"), abs=1e-9
    )


def test_boxes_follow_the_scroll_unless_fixed(attention: AttentionParams) -> None:
    # Medidos sin scroll: un párrafo en y = 900 y una barra fija en y = 600.
    screen = layouts(
        (
            0,
            [
                element("#below", 100, 900, 400, 60, tag="p"),
                element("#bar", 100, 600, 400, 60, tag="nav", fixed=True),
            ],
        )
    )

    # Con 500 px de scroll el párrafo sube a y = 400; la barra fija sigue en y = 600.
    on_paragraph = run(attention, samples((1000, 1300, 300, 430), scroll_y=500), screen)
    on_bar = run(attention, samples((1000, 1300, 300, 630), scroll_y=500), screen)

    assert on_paragraph.fixations.iloc[0]["element_selector"] == "#below"
    assert on_paragraph.fixations.iloc[0]["element_p"] > 0.9
    assert on_bar.fixations.iloc[0]["element_selector"] == "#bar"
    assert on_bar.fixations.iloc[0]["element_p"] > 0.9


def test_a_long_fixation_without_activity_is_a_long_stare(attention: AttentionParams) -> None:
    long_ms = attention.long_stare_ms
    gaze = samples(
        (1000, 1000 + long_ms + 500, 300, 130),
        (5000, 5000 + long_ms + 500, 300, 130),
        (9000, 9300, 300, 130),
    )

    result = run(
        attention,
        gaze,
        layouts((0, TITLE_AND_SEARCH)),
        interactions((6000, "scroll", None)),
    )

    assert result.fixations["long_stare"].tolist() == [True, False, False]


def test_layouts_before_version_1_6_have_only_interactive_elements(
    attention: AttentionParams,
) -> None:
    old = [
        {key: value for key, value in e.items() if key not in ("interactive", "parent")}
        for e in TITLE_AND_SEARCH
    ]

    result = run(attention, samples((1000, 1300, 300, 130)), layouts((0, old)))

    assert result.fixations.iloc[0]["element_selector"] == "#title"
    assert result.candidates.set_index("selector").loc["#title", "interactive"]


def test_fixations_before_the_first_layout_are_left_out(attention: AttentionParams) -> None:
    result = run(
        attention,
        samples((1000, 1300, 300, 130), (3000, 3300, 300, 130)),
        layouts((2000, TITLE_AND_SEARCH)),
    )

    assert result.fixations["fixation"].tolist() == [1]


def test_without_fixations_or_layouts_the_tables_are_empty(attention: AttentionParams) -> None:
    empty = run(attention, columns.empty("gaze_refined"), layouts((0, TITLE_AND_SEARCH)))
    no_layout = run(attention, samples((1000, 1300, 300, 130)), columns.empty("layouts"))

    for result in (empty, no_layout):
        columns.validate(result.fixations, "gaze_fixation")
        columns.validate(result.candidates, "gaze_attribution")
        assert result.fixations.empty


def test_the_error_comes_from_the_session_or_the_default(attention: AttentionParams) -> None:
    measured = error_sigma_px(2.0, SETTINGS, attention)
    default = error_sigma_px(None, SETTINGS, attention)

    assert measured == pytest.approx(
        2.0 * attention.natural_error_factor / math.sqrt(math.pi / 2) * PX_PER_DEG
    )
    assert default == pytest.approx(measured / 2.0 * attention.default_error_deg)


def test_probability_seen_combines_the_fixations_of_a_stretch(
    attention: AttentionParams,
) -> None:
    result = run(
        attention,
        samples((1000, 1300, 510, 130), (1400, 1700, 510, 130), (9000, 9300, 300, 130)),
        layouts((0, TITLE_AND_SEARCH)),
        interactions((1800, "click", "#search")),
    )
    p = [p_of(result, k, "#search", "p_gaze") for k in (0, 1)]

    seen = probability_seen(result.candidates, result.fixations, "#search", 900, 2000)

    assert seen == pytest.approx(1 - (1 - p[0]) * (1 - p[1]))
    assert (
        probability_seen(result.candidates, result.fixations, "#search", 900, 2000, attention=True)
        > seen
    )
    assert probability_seen(result.candidates, result.fixations, "#search", 5000, 6000) == 0.0


def test_the_probabilities_are_calibrated_on_a_simulated_session(
    attention: AttentionParams,
) -> None:
    """Con verdad conocida, la probabilidad informada coincide con el acierto.

    Se simula el modelo que supone la atribución: con ``unassigned_prior`` la
    persona mira un punto cualquiera de la ventana; si no, un punto de un
    elemento elegido al azar. La medición se corre con el error supuesto. Si las
    probabilidades son honestas, de las fijaciones con ~70 % acierta ~70 %.
    """
    rng = np.random.default_rng(7)
    params = replace(attention, natural_error_factor=1.0)
    sigma = error_sigma_px(1.5, SETTINGS, params)
    grid = [
        element(f"#e{row}{col}", 40 + col * 190, 40 + row * 150, w, h)
        for row in range(5)
        for col in range(6)
        for w, h in [(rng.uniform(60, 170), rng.uniform(25, 120))]
    ]
    boxes = np.array([[e["box"]["x"], e["box"]["y"], e["box"]["w"], e["box"]["h"]] for e in grid])
    fixations, truth = [], []
    for k in range(2500):
        if rng.random() < attention.unassigned_prior:
            point, true = rng.uniform([0, 0], [1200, 800]), None
        else:
            index = int(rng.integers(len(grid)))
            x, y, w, h = boxes[index]
            point, true = rng.uniform([x, y], [x + w, y + h]), grid[index]["selector"]
        measured = point + rng.normal(0, sigma, 2)
        # Fijaciones separadas por más que el hueco máximo: cada una se juzga sola.
        start = k * 5000.0
        fixations.append((start, start + 200, *measured))
        truth.append(true)

    result = run(params, samples(*fixations), layouts((0, grid)), error_deg=1.5)

    rows = result.fixations.sort_values("fixation")
    best_p = np.where(
        rows["unassigned_p"] > rows["element_p"].fillna(0), rows["unassigned_p"], rows["element_p"]
    )
    guess = np.where(
        rows["unassigned_p"] > rows["element_p"].fillna(0), None, rows["element_selector"]
    )
    correct = np.array([g == t for g, t in zip(guess, truth, strict=True)])
    bins = np.digitize(best_p, [0.4, 0.6, 0.8, 0.95])
    checked = 0
    for b in np.unique(bins):
        chosen = bins == b
        if chosen.sum() >= 100:
            assert abs(best_p[chosen].mean() - correct[chosen].mean()) < 0.06
            checked += 1
    assert checked >= 3
    # La atribución acierta más que quedarse con el elemento que contiene el punto.
    inside = []
    for x, y in rows[["x", "y"]].to_numpy():
        hit = (boxes[:, 0] <= x) & (x < boxes[:, 0] + boxes[:, 2])
        hit &= (boxes[:, 1] <= y) & (y < boxes[:, 1] + boxes[:, 3])
        inside.append(grid[int(np.argmax(hit))]["selector"] if hit.any() else None)
    baseline = np.mean([g == t for g, t in zip(inside, truth, strict=True)])
    assert correct.mean() > baseline


def _store_layout(connection: sqlite3.Connection, tmp_path: Path) -> None:
    """Guarda en la sesión 1 la disposición de ejemplo, como el servidor."""
    writer = SqliteRepository(connection, tmp_path)
    example = ROOT_DIR / "contracts" / "examples" / "layout.valid.json"
    with writer.transaction():
        handler_for("layout")(writer, 1, [json.loads(example.read_text(encoding="utf-8"))])


def test_the_attribution_is_saved_and_replaced(
    connection: sqlite3.Connection, repository: SqliteAnalysisRepository, attention: AttentionParams
) -> None:
    result = run(
        attention,
        samples((1000, 1300, 510, 130), (2000, 2300, 1000, 650)),
        layouts((0, TITLE_AND_SEARCH)),
    )

    repository.save_gaze_attention(1, result.fixations, result.candidates)
    repository.save_gaze_attention(1, result.fixations, result.candidates)

    count = connection.execute("SELECT COUNT(*) FROM gaze_fixation").fetchone()[0]
    assert count == 2
    unassigned = connection.execute(
        "SELECT COUNT(*) FROM gaze_attribution WHERE selector IS NULL"
    ).fetchone()[0]
    assert unassigned == 2


def test_an_invalid_attribution_leaves_the_database_untouched(
    connection: sqlite3.Connection, repository: SqliteAnalysisRepository
) -> None:
    with pytest.raises(columns.ColumnValidationError):
        repository.save_gaze_attention(
            1, pd.DataFrame({"fixation": [1]}), columns.empty("gaze_attribution")
        )
    assert connection.execute("SELECT COUNT(*) FROM gaze_fixation").fetchone()[0] == 0


def test_the_repository_loads_the_interactions_with_their_selector(
    repository: SqliteAnalysisRepository,
) -> None:
    inputs = repository.load_gaze_inputs(1)

    clicks = inputs.interactions[inputs.interactions["type"] == "click"]
    assert "#pay" in clicks["selector"].tolist()
    assert "mousemove" not in inputs.interactions["type"].tolist()


def test_the_analysis_attributes_the_gaze_after_refining_it(
    connection: sqlite3.Connection,
    repository: SqliteAnalysisRepository,
    params: Parameters,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _store_layout(connection, tmp_path)
    writer = SqliteRepository(connection, tmp_path)
    example = ROOT_DIR / "contracts" / "examples" / "gaze_features.valid.json"
    frame = json.loads(example.read_text(encoding="utf-8"))
    with writer.transaction():
        # Diez cuadros quietos forman una fijación.
        handler_for("gaze_features")(
            writer, 1, [{**frame, "t": frame["t"] + 33 * i} for i in range(10)]
        )

    analyze_session(repository, 1, params, gaze=(repository, SETTINGS))

    assert "gaze attribution failed" not in caplog.text
    assert connection.execute("SELECT COUNT(*) FROM gaze_fixation").fetchone()[0] == 1


def test_a_failed_attribution_keeps_the_refined_gaze(
    connection: sqlite3.Connection,
    repository: SqliteAnalysisRepository,
    params: Parameters,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _store_layout(connection, tmp_path)
    writer = SqliteRepository(connection, tmp_path)
    example = ROOT_DIR / "contracts" / "examples" / "gaze_features.valid.json"
    with writer.transaction():
        handler_for("gaze_features")(writer, 1, [json.loads(example.read_text(encoding="utf-8"))])

    class Broken:
        def load_gaze_inputs(self, session_id: int) -> GazeInputs:
            return repository.load_gaze_inputs(session_id)

        def save_gaze_refinement(self, *args: object) -> None:
            repository.save_gaze_refinement(*args)  # type: ignore[arg-type]

        def save_gaze_attention(self, *args: object) -> None:
            raise RuntimeError("disk on fire")

    results = analyze_session(repository, 1, params, gaze=(Broken(), SETTINGS))

    assert results.gaze_quality is not None
    assert "gaze attribution failed: disk on fire" in caplog.text
    assert connection.execute("SELECT COUNT(*) FROM gaze_refined").fetchone()[0] == 1
