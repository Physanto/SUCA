"""Genera ``extension/config.generated.js`` desde la configuración y los contratos.

La extensión no puede leer archivos fuera de su carpeta, así que recibe aquí una
copia de solo lo que necesita:

- ``UX.config``: las secciones ``server``, ``sending``, ``capture`` y ``camera``
  de ``config/shared.json``;
- ``UX.contracts``: la versión de los contratos y sus enumeraciones, para que
  ningún valor se escriba a mano en JavaScript.

El archivo generado se versiona y una prueba comprueba que está al día. Uso::

    python -m scripts.generate_config
"""

import dataclasses
import json
from string import Template
from typing import Any

from shared import contracts
from shared.config import ROOT_DIR, Config, load_config

OUTPUT_PATH = ROOT_DIR / "extension" / "config.generated.js"
"""Archivo que se genera."""

EXTENSION_SECTIONS = ("server", "sending", "capture", "camera")
"""Secciones de la configuración que necesita la extensión. El resto no se copia."""

_TEMPLATE = Template(
    """\
/**
 * @file Configuración y contratos para la extensión.
 *
 * ARCHIVO GENERADO: no lo edites a mano. Se genera con
 * `python -m scripts.generate_config` desde config/shared.json y
 * contracts/enums.json; una prueba falla si queda desactualizado.
 *
 * Define `UX.config` y `UX.contracts` sobre globalThis, así que funciona igual
 * en los content scripts, en el service worker (importScripts) y en el panel.
 */

(function (root) {
  'use strict';

  /**
   * Congela un objeto y todo lo que contiene, para que ningún módulo pueda
   * alterar los valores compartidos.
   *
   * @param {object} value - Objeto a congelar.
   * @returns {object} El mismo objeto, congelado.
   */
  function deepFreeze(value) {
    Object.values(value).forEach((child) => {
      if (child !== null && typeof child === 'object') {
        deepFreeze(child);
      }
    });
    return Object.freeze(value);
  }

  const UX = (root.UX = root.UX || {});

  /** Configuración de la extensión: servidor, envío, captura y cámara. */
  UX.config = deepFreeze($config);

  /** Versión de los contratos y valores permitidos de cada enumeración. */
  UX.contracts = deepFreeze($contracts);
})(globalThis);
"""
)


def extension_config(config: Config) -> dict[str, Any]:
    """Selecciona la parte de la configuración que necesita la extensión.

    Args:
        config: Configuración completa.

    Returns:
        Diccionario con solo las secciones de ``EXTENSION_SECTIONS``.
    """
    return {name: dataclasses.asdict(getattr(config, name)) for name in EXTENSION_SECTIONS}


def extension_contracts() -> dict[str, Any]:
    """Reúne la versión y las enumeraciones de los contratos.

    Returns:
        Diccionario con ``version`` y ``enums`` (nombre → lista de valores).
    """
    return {
        "version": contracts.contract_version(),
        "enums": {name: list(values) for name, values in contracts.enums().items()},
    }


def render(config: Config) -> str:
    """Genera el contenido de ``config.generated.js``.

    Args:
        config: Configuración completa.

    Returns:
        Código JavaScript del archivo, con saltos de línea de Unix.
    """
    return _TEMPLATE.substitute(
        config=_to_js(extension_config(config)),
        contracts=_to_js(extension_contracts()),
    )


def _to_js(value: dict[str, Any]) -> str:
    """Convierte un diccionario en un literal de JavaScript indentado.

    JSON es un subconjunto válido de JavaScript; solo se ajusta la sangría al
    nivel donde se inserta.

    Args:
        value: Diccionario serializable a JSON.

    Returns:
        Literal de objeto listo para insertar en la plantilla.
    """
    return json.dumps(value, indent=2).replace("\n", "\n  ")


def main() -> None:
    """Escribe ``extension/config.generated.js`` con la configuración actual."""
    OUTPUT_PATH.write_text(render(load_config()), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT_PATH.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
