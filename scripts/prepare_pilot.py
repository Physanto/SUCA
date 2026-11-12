"""Genera un YAML de piloto para una app externa sin registrar texto de campos.

Después se carga con scripts.load_study. No crea sesiones ni participantes.
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from shared import contracts


def prepare(name: str, url: str, tasks: list[str], output: Path) -> None:
    """Escribe un estudio validado con 2–4 tareas y sin sobrescribir archivos.

    Args:
        name: Nombre único del estudio.
        url: Dirección HTTP o HTTPS de la aplicación real.
        tasks: Instrucciones concretas del participante.
        output: Archivo YAML nuevo.

    Raises:
        ValueError: Si no cumple el contrato o las condiciones del piloto.
        FileExistsError: Si ya existe el archivo solicitado.
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("pilot URL must use HTTP(S), have a host and contain no credentials")
    if not 2 <= len(tasks) <= 4 or any(not task.strip() for task in tasks):
        raise ValueError("pilot needs two to four nonempty task instructions")
    document = {
        "name": name.strip(),
        "system_under_test": url,
        "description": "Piloto del flujo completo de captura, incidentes, IUC y mapas. "
        "No mide por sí solo la precisión de la mirada.",
        "tasks": [{"instruction": task.strip()} for task in tasks],
        "recorded_fields": [],
    }
    errors = contracts.validate("study", document)
    if errors:
        raise ValueError(f"invalid pilot study: {errors}")
    with output.open("x", encoding="utf-8") as target:
        target.write(yaml.safe_dump(document, allow_unicode=True, sort_keys=False))


def main(argv: list[str] | None = None) -> int:
    """Genera el estudio a partir de URL y tareas proporcionadas por el evaluador."""
    parser = argparse.ArgumentParser(description="Prepara un estudio piloto para una app real.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--task", required=True, action="append")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        prepare(args.name, args.url, args.task, args.output)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Estudio preparado: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
