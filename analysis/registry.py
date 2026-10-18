"""Registro genérico de estrategias (Strategy + Registry).

Las etapas que admiten variantes (detectores de incidentes, detectores de
episodios) tienen un registro. Cada variante es una clase que se registra con
un decorador; la etapa ejecuta todas las registradas sin conocerlas por
nombre. Agregar una variante no cambia la etapa.

Ejemplo::

    DETECTORS = Registry("detector", key="incident_type", allowed=enums["incident_type"])

    @DETECTORS.register
    class RageClickDetector:
        incident_type = "rage_click"

        def find(self, data, params): ...
"""

from collections.abc import Iterable
from typing import Any, Generic, TypeVar

_T = TypeVar("_T")


class RegistryError(ValueError):
    """Una estrategia no se puede registrar o no existe."""


class Registry(Generic[_T]):
    """Estrategias de un mismo tipo, por nombre y en orden de registro.

    Args:
        kind: Qué se registra, para los mensajes (``detector``…).
        key: Atributo de cada estrategia que la nombra (``incident_type``…).
        allowed: Nombres permitidos, normalmente una enumeración del contrato;
            ``None`` admite cualquiera.
    """

    def __init__(self, kind: str, *, key: str, allowed: Iterable[str] | None = None) -> None:
        """Crea un registro vacío."""
        self.kind = kind
        self.key = key
        self._allowed = None if allowed is None else frozenset(allowed)
        self._strategies: dict[str, _T] = {}

    def register(self, cls: type[_T]) -> type[_T]:
        """Registra una clase de estrategia. Se usa como decorador.

        La clase se instancia sin argumentos; su nombre es el valor del
        atributo ``key``.

        Args:
            cls: Clase de la estrategia.

        Returns:
            La misma clase, sin cambios, para poder usarla también directamente.

        Raises:
            RegistryError: Si no tiene el atributo ``key``, si su nombre no está
                permitido o si ya hay una estrategia con ese nombre.
        """
        strategy = cls()
        name: Any = getattr(strategy, self.key, None)
        if not isinstance(name, str) or not name:
            raise RegistryError(f"{self.kind} {cls.__name__} must define {self.key!r} as a string")
        if self._allowed is not None and name not in self._allowed:
            raise RegistryError(
                f"{self.kind} {cls.__name__}: {name!r} is not one of {sorted(self._allowed)}"
            )
        if name in self._strategies:
            raise RegistryError(f"{self.kind} {name!r} is already registered")
        self._strategies[name] = strategy
        return cls

    def get(self, name: str) -> _T:
        """Devuelve la estrategia de un nombre.

        Args:
            name: Nombre de la estrategia.

        Returns:
            La estrategia registrada.

        Raises:
            RegistryError: Si no hay ninguna con ese nombre.
        """
        try:
            return self._strategies[name]
        except KeyError:
            raise RegistryError(
                f"no {self.kind} named {name!r}; registered: {list(self._strategies)}"
            ) from None

    def all(self) -> tuple[_T, ...]:
        """Devuelve todas las estrategias, en orden de registro.

        Returns:
            Estrategias registradas.
        """
        return tuple(self._strategies.values())

    def names(self) -> tuple[str, ...]:
        """Devuelve los nombres registrados, en orden de registro.

        Returns:
            Nombres.
        """
        return tuple(self._strategies)

    def __len__(self) -> int:
        """Cantidad de estrategias registradas."""
        return len(self._strategies)
