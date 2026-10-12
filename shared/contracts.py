"""Validación de documentos contra los contratos de ``contracts/``.

Es una fachada sobre jsonschema y el único módulo del proyecto que lo usa. Carga
los esquemas y las enumeraciones una sola vez y devuelve los errores como
valores simples (ruta del campo y motivo), sin exponer tipos de la librería.

Cada archivo ``*.schema.json`` define un tipo de documento validable, cuyo nombre
es el del archivo sin la extensión: ``batch``, ``element``, ``reference`` y uno
por tipo de lote (``events``, ``gaze``…). Agregar un esquema no requiere cambiar
este módulo.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"
"""Carpeta de los contratos, en la raíz del repositorio."""

_SCHEMA_SUFFIX = ".schema.json"
_ENUMS_FILE = "enums.json"
_VERSION_SCHEMA = "batch.schema.json"


class UnknownContractError(LookupError):
    """Se pidió validar un tipo de documento que no tiene esquema."""


@dataclass(frozen=True)
class ContractError:
    """Un motivo por el que un documento no cumple su contrato.

    Attributes:
        path: Ruta del campo con el problema desde la raíz del documento. Las
            posiciones en listas son enteros. Vacía si el problema es del
            documento completo.
        message: Motivo, en inglés, como todo mensaje técnico.
    """

    path: tuple[str | int, ...]
    message: str

    def __str__(self) -> str:
        """Devuelve el error como ``ruta/del/campo: motivo``."""
        location = "/".join(str(part) for part in self.path) or "<root>"
        return f"{location}: {self.message}"


def validate(kind: str, document: Any) -> list[ContractError]:
    """Valida un documento contra el esquema de su tipo.

    Args:
        kind: Tipo de documento, uno de los que devuelve ``kinds()``.
        document: Documento ya decodificado desde JSON.

    Returns:
        Errores encontrados, ordenados por ruta. Vacía si el documento es válido.

    Raises:
        UnknownContractError: Si ``kind`` no tiene esquema.
    """
    validator = _validator(kind)
    errors = [_to_contract_error(error) for error in validator.iter_errors(document)]
    return sorted(errors, key=_sort_key)


def kinds() -> tuple[str, ...]:
    """Devuelve los tipos de documento que se pueden validar.

    Returns:
        Nombres de los tipos, en orden alfabético.
    """
    return tuple(sorted(_schema_paths()))


@cache
def enums() -> Mapping[str, tuple[str, ...]]:
    """Devuelve las enumeraciones de ``contracts/enums.json``.

    Returns:
        Diccionario de solo lectura: nombre de la enumeración (por ejemplo,
        ``event_type``) y sus valores, en el orden del contrato.
    """
    definitions = _documents()[_ENUMS_FILE]["$defs"]
    return MappingProxyType(
        {name: tuple(definition["enum"]) for name, definition in definitions.items()}
    )


@cache
def contract_version() -> str:
    """Devuelve la versión actual de los contratos.

    Es el valor por defecto de ``contract_version`` en el esquema del lote.

    Returns:
        Versión semántica, por ejemplo ``"1.0.0"``.
    """
    schema = _documents()[_VERSION_SCHEMA]
    return schema["properties"]["contract_version"]["default"]


@cache
def _documents() -> dict[str, dict[str, Any]]:
    """Carga todos los archivos JSON de contratos, salvo los ejemplos.

    Returns:
        Documentos indexados por su ruta relativa a ``CONTRACTS_DIR``, con ``/``.
    """
    documents = {}
    for path in sorted(CONTRACTS_DIR.rglob("*.json")):
        relative = path.relative_to(CONTRACTS_DIR)
        if relative.parts[0] == "examples":
            continue
        documents[relative.as_posix()] = json.loads(path.read_text(encoding="utf-8"))
    return documents


@cache
def _schema_paths() -> dict[str, str]:
    """Asocia cada tipo de documento con la ruta de su esquema.

    Returns:
        Ruta relativa del esquema por tipo de documento.

    Raises:
        RuntimeError: Si dos esquemas producen el mismo tipo de documento.
    """
    paths: dict[str, str] = {}
    for relative in _documents():
        if not relative.endswith(_SCHEMA_SUFFIX):
            continue
        kind = relative.rsplit("/", 1)[-1].removesuffix(_SCHEMA_SUFFIX)
        if kind in paths:
            raise RuntimeError(f"duplicate contract kind {kind!r}: {paths[kind]}, {relative}")
        paths[kind] = relative
    return paths


@cache
def _registry() -> Registry:
    """Registra todos los contratos por su ``$id``.

    Así los ``$ref`` entre archivos se resuelven en memoria, sin acceso a la red.

    Returns:
        Registro de referencias de jsonschema.
    """
    resources = [
        (document["$id"], Resource.from_contents(document)) for document in _documents().values()
    ]
    return Registry().with_resources(resources)


@cache
def _validator(kind: str) -> Draft202012Validator:
    """Crea, una sola vez por tipo, el validador de un tipo de documento.

    Args:
        kind: Tipo de documento.

    Returns:
        Validador listo para usar.

    Raises:
        UnknownContractError: Si ``kind`` no tiene esquema.
    """
    paths = _schema_paths()
    if kind not in paths:
        raise UnknownContractError(f"unknown contract kind {kind!r}; expected one of {kinds()}")
    return Draft202012Validator(_documents()[paths[kind]], registry=_registry())


def _to_contract_error(error: ValidationError) -> ContractError:
    """Convierte un error de jsonschema en un ``ContractError``.

    Los errores de ``anyOf`` y ``oneOf`` solo dicen que ninguna opción encajó.
    Se baja al error más específico, descartando las opciones que fallan solo
    porque el valor es de otro tipo: así un objeto mal formado en un campo que
    admite ``null`` se informa por su problema real y no como "no es null".

    Args:
        error: Error de jsonschema.

    Returns:
        Error con la ruta y el motivo más específicos disponibles.
    """
    specific = best_match([error])
    while specific.context:
        same_type = [
            sub
            for sub in specific.context
            if not (sub.validator == "type" and not sub.relative_path)
        ]
        specific = best_match(same_type or specific.context)
    return ContractError(path=tuple(specific.absolute_path), message=specific.message)


def _sort_key(error: ContractError) -> list[tuple[int, int, str]]:
    """Clave para ordenar errores por ruta, con las posiciones en orden numérico.

    Args:
        error: Error a ordenar.

    Returns:
        Clave comparable aunque la ruta mezcle textos y enteros.
    """
    return [
        (0, part, "") if isinstance(part, int) else (1, 0, part) for part in error.path
    ]
