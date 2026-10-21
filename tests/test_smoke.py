"""Prueba de humo: los paquetes del proyecto se importan sin tocar sys.path."""

import importlib

import pytest


@pytest.mark.parametrize("package", ["shared", "server", "analysis", "dashboard", "scripts"])
def test_project_packages_are_importable(package: str) -> None:
    assert importlib.import_module(package) is not None
