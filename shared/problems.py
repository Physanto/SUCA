"""Catálogo de problemas sembrados de un estudio: dónde ocurren y qué los detecta.

El catálogo es un YAML (por ejemplo, ``studies/example-problems.yaml``) con, por
problema, las versiones en que está activo, la tarea y las pantallas donde
ocurre y los tipos de incidente que deberían detectarlo.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shared import contracts


class CatalogError(ValueError):
    """El catálogo no tiene la forma esperada."""


@dataclass(frozen=True)
class SeededProblem:
    """Un problema sembrado del sistema evaluado.

    Attributes:
        number: Número del problema.
        key: Clave corta (la de la app de prueba).
        name: Descripción legible.
        versions: Versiones en que está activo.
        task: Posición de la tarea en que ocurre, o ``None`` si es fuera de las tareas.
        screens: Pantallas normalizadas donde ocurre; vacío, cualquiera.
        detectors: Tipos de incidente que deberían detectarlo.
    """

    number: int
    key: str
    name: str
    versions: tuple[str, ...]
    task: int | None
    screens: tuple[str, ...]
    detectors: tuple[str, ...]

    def matches(self, incident_type: str, task_position: int | None, screen: str | None) -> bool:
        """Indica si un incidente es evidencia de este problema.

        Args:
            incident_type: Tipo del incidente.
            task_position: Posición de la tarea del incidente, o ``None``.
            screen: Pantalla normalizada del incidente.

        Returns:
            ``True`` si coinciden el tipo, la tarea y (si se indicaron) la pantalla.
        """
        if incident_type not in self.detectors or task_position != self.task:
            return False
        return not self.screens or screen in self.screens


@dataclass(frozen=True)
class Catalog:
    """Problemas sembrados de un estudio.

    Attributes:
        study: Nombre del estudio.
        problems: Problemas, en orden de número.
    """

    study: str
    problems: tuple[SeededProblem, ...]

    def active(self, version: str) -> tuple[SeededProblem, ...]:
        """Problemas activos en una versión."""
        return tuple(problem for problem in self.problems if version in problem.versions)

    def overlapping(self, problem: SeededProblem, version: str) -> tuple[int, ...]:
        """Otros problemas activos en la versión que comparten tarea y algún detector.

        Sus evidencias no se distinguen: un mismo incidente cuenta para ambos.
        """
        return tuple(
            other.number
            for other in self.active(version)
            if other.number != problem.number
            and other.task == problem.task
            and set(other.detectors) & set(problem.detectors)
            and (
                not other.screens
                or not problem.screens
                or set(other.screens) & set(problem.screens)
            )
        )


def load_catalog(path: Path) -> Catalog:
    """Lee y valida un catálogo de problemas sembrados.

    Args:
        path: Archivo YAML.

    Returns:
        El catálogo.

    Raises:
        CatalogError: Si falta un campo, un tipo de incidente no existe en el
            contrato o se repite un número.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise CatalogError(f"cannot read the catalog {path}: {error}") from error
    if not isinstance(document, Mapping) or not isinstance(document.get("problems"), list):
        raise CatalogError(f"{path}: expected a mapping with a 'problems' list")
    incident_types = set(contracts.enums()["incident_type"])
    problems = [
        _problem(item, index, incident_types) for index, item in enumerate(document["problems"])
    ]
    numbers = [problem.number for problem in problems]
    if len(set(numbers)) != len(numbers):
        raise CatalogError(f"{path}: problem numbers must be unique")
    return Catalog(str(document.get("study", "")), tuple(sorted(problems, key=lambda p: p.number)))


def _problem(item: Any, index: int, incident_types: set[str]) -> SeededProblem:
    """Valida un problema del catálogo."""
    where = f"problems[{index}]"
    if not isinstance(item, Mapping):
        raise CatalogError(f"{where}: expected a mapping")
    for field in ("number", "key", "name", "versions", "detectors"):
        if field not in item:
            raise CatalogError(f"{where}: missing '{field}'")
    task = item.get("task")
    if task is not None and (not isinstance(task, int) or task < 1):
        raise CatalogError(f"{where}: 'task' must be a positive position or null")
    detectors = _strings(item["detectors"], f"{where}.detectors")
    unknown = sorted(set(detectors) - incident_types)
    if unknown:
        raise CatalogError(f"{where}: unknown incident types {unknown}")
    versions = _strings(item["versions"], f"{where}.versions")
    if not versions or not detectors:
        raise CatalogError(f"{where}: 'versions' and 'detectors' cannot be empty")
    return SeededProblem(
        number=int(item["number"]),
        key=str(item["key"]),
        name=str(item["name"]),
        versions=versions,
        task=task,
        screens=_strings(item.get("screens") or [], f"{where}.screens"),
        detectors=detectors,
    )


def _strings(value: Any, where: str) -> tuple[str, ...]:
    """Lista de textos, o error."""
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise CatalogError(f"{where}: expected a list")
    if not all(isinstance(item, str) and item for item in value):
        raise CatalogError(f"{where}: expected non-empty strings")
    return tuple(value)
