"""Pruebas del registro genérico de estrategias."""

import pytest

from analysis import detectors, episodes
from analysis.registry import Registry, RegistryError


def new_registry() -> Registry:
    """Registro de prueba con nombres permitidos."""
    return Registry("detector", key="incident_type", allowed=["rage_click", "dead_click"])


def test_registers_classes_with_a_decorator_in_order() -> None:
    registry = new_registry()

    @registry.register
    class RageClick:
        incident_type = "rage_click"

    @registry.register
    class DeadClick:
        incident_type = "dead_click"

    assert registry.names() == ("rage_click", "dead_click")
    assert [type(item) for item in registry.all()] == [RageClick, DeadClick]
    assert isinstance(registry.get("dead_click"), DeadClick)
    assert len(registry) == 2
    # El decorador devuelve la clase sin cambios.
    assert RageClick.incident_type == "rage_click"


def test_rejects_repeated_missing_and_not_allowed_names() -> None:
    registry = new_registry()

    class First:
        incident_type = "rage_click"

    class Again:
        incident_type = "rage_click"

    class Nameless:
        pass

    class Unknown:
        incident_type = "slow_click"

    registry.register(First)
    with pytest.raises(RegistryError, match="'rage_click' is already registered"):
        registry.register(Again)
    with pytest.raises(RegistryError, match="Nameless must define 'incident_type'"):
        registry.register(Nameless)
    with pytest.raises(RegistryError, match="'slow_click' is not one of"):
        registry.register(Unknown)


def test_get_reports_the_registered_names() -> None:
    registry = new_registry()

    with pytest.raises(RegistryError, match=r"no detector named 'rage_click'; registered: \[\]"):
        registry.get("rage_click")


def test_without_allowed_names_any_name_is_accepted() -> None:
    registry = Registry("strategy", key="name")

    @registry.register
    class Anything:
        name = "anything"

    assert registry.names() == ("anything",)


def test_stage_registries_only_accept_contract_types() -> None:
    class Unknown:
        incident_type = "rageclick"
        episode_type = "checkout"

    assert detectors.DETECTORS.names() == (
        "rage_click",
        "dead_click",
        "navigation_loop",
        "long_pause",
        "hesitation",
        "task_overtime",
        "form_error",
        "field_reentry",
        "form_abandonment",
        "repeated_search",
    )
    assert episodes.EPISODE_DETECTORS.names() == ("login", "form", "search", "screen")
    with pytest.raises(RegistryError, match="not one of"):
        detectors.DETECTORS.register(Unknown)
    with pytest.raises(RegistryError, match="not one of"):
        episodes.EPISODE_DETECTORS.register(Unknown)
