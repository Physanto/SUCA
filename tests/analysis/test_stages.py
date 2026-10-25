"""Pruebas de los esqueletos de las etapas y de las fachadas de estrategias."""

import pandas as pd
import pytest

from analysis import cleaning, columns, detectors, episodes, reference, screens, usability_index
from analysis.columns import ColumnValidationError
from analysis.loader import SessionData, SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.registry import Registry
from shared import contracts


def incident_registry(*classes: type) -> Registry:
    """Registro de detectores de prueba, con los tipos del contrato."""
    registry = Registry("detector", key="incident_type", allowed=contracts.enums()["incident_type"])
    for cls in classes:
        registry.register(cls)
    return registry


class LateClicks:
    """Detector de prueba: un incidente por cada clic, al final de la lista."""

    incident_type = "dead_click"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Marca cada clic."""
        clicks = data.events[data.events["type"] == "click"]
        return columns.frame(
            "incident",
            [
                {"type": "dead_click", "t": row.t, "screen": row.screen, "task_id": row.task_id}
                for row in clicks.itertuples()
            ],
        )


class EarlyPause:
    """Detector de prueba: una pausa al inicio de la sesión."""

    incident_type = "long_pause"

    def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
        """Marca una pausa en el primer evento."""
        first = data.events.iloc[0]
        return columns.frame("incident", [{"type": "long_pause", "t": first["t"]}])


@pytest.fixture
def data(repository: SqliteAnalysisRepository) -> SessionData:
    """Datos de la sesión guiada de la base pequeña."""
    return repository.load_session(1)


def test_cleaning_and_screens_return_the_data_unchanged(
    data: SessionData, params: Parameters
) -> None:
    assert cleaning.clean(data, params) is data
    assert screens.assign_screens(data, params) is data


def test_reference_measures_tasks_and_index_waits_for_a_threshold(
    data: SessionData, params: Parameters
) -> None:
    task_results = reference.compare(data, params)
    index = usability_index.compute(data, task_results, columns.empty("incident"), params)

    assert len(task_results) == 1
    assert not task_results.iloc[0]["success"]
    assert len(index) == 0
    columns.validate(task_results, "task_result")
    columns.validate(index, "usability_index")


def test_without_strategies_the_facades_return_empty_frames(
    data: SessionData, params: Parameters
) -> None:
    incidents = detectors.detect(data, params)
    found = episodes.detect(data, params)

    assert len(incidents) == 0
    assert len(found) == 0
    columns.validate(incidents, "incident")
    columns.validate(found, "episode")


def test_detect_joins_the_results_of_every_detector_in_time_order(
    data: SessionData, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(detectors, "DETECTORS", incident_registry(LateClicks, EarlyPause))

    incidents = detectors.detect(data, params)

    assert list(incidents["type"]) == ["long_pause", "dead_click"]
    assert incidents["t"].is_monotonic_increasing
    columns.validate(incidents, "incident")


def test_a_detector_with_wrong_columns_is_named(
    data: SessionData, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        incident_type = "rage_click"

        def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
            return pd.DataFrame({"type": ["rage_click"], "time": [1.0]})

    monkeypatch.setattr(detectors, "DETECTORS", incident_registry(Broken))

    with pytest.raises(ColumnValidationError, match="detector rage_click: missing columns"):
        detectors.detect(data, params)


def test_a_detector_that_returns_other_types_is_rejected(
    data: SessionData, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Mislabeled:
        incident_type = "rage_click"

        def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
            return columns.frame("incident", [{"type": "dead_click", "t": 1.0}])

    monkeypatch.setattr(detectors, "DETECTORS", incident_registry(Mislabeled))

    with pytest.raises(ColumnValidationError, match=r"other types: \['dead_click'\]"):
        detectors.detect(data, params)


def test_a_detector_that_fails_is_named(
    data: SessionData, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing:
        incident_type = "hesitation"

        def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
            raise KeyError("cursor")

    monkeypatch.setattr(detectors, "DETECTORS", incident_registry(Failing))

    with pytest.raises(RuntimeError, match="detector hesitation failed: 'cursor'"):
        detectors.detect(data, params)


def test_episode_detectors_are_joined_by_start_time(
    data: SessionData, params: Parameters, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Screens:
        episode_type = "screen"

        def find(self, data: SessionData, params: Parameters) -> pd.DataFrame:
            rows = [
                {"type": "screen", "t_start": t, "t_end": t + 1, "screen": "/"}
                for t in sorted(data.events["t"], reverse=True)
            ]
            return columns.frame("episode", rows)

    registry = Registry(
        "episode detector", key="episode_type", allowed=contracts.enums()["episode_type"]
    )
    registry.register(Screens)
    monkeypatch.setattr(episodes, "EPISODE_DETECTORS", registry)

    found = episodes.detect(data, params)

    assert len(found) == 3
    assert found["t_start"].is_monotonic_increasing
