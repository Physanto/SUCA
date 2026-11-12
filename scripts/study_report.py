r"""Genera el informe de resultados de un estudio: un archivo HTML redactado y con gráficas.

Reúne el veredicto (SUS, tareas, IUC y hallazgos), el SUS desglosado por ítem, los
hallazgos con lo que significan, los mapas de calor, la línea de tiempo y la
relación orientativa con las heurísticas de Nielsen. Funciona sin internet y se
imprime a PDF desde el navegador. Solo lee la base.

El informe contiene datos de participantes y capturas de la aplicación evaluada:
queda en ``data/reports/`` (que no se versiona) y no debe subirse a ningún servicio.

Uso::

    python -m scripts.study_report --study 1
    python -m scripts.study_report --study 1 --modes guided --versions V0 V2 \
        --conclusions conclusiones.txt --output data/reports/informe.html

Antes, analiza las sesiones con ``python -m analysis.run --study ID``. También se
genera desde la página **Informe** del panel, donde se pueden escribir las
recomendaciones de cada hallazgo.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from dashboard import report, report_inputs
from dashboard.data import open_data
from shared import db
from shared.config import ConfigError, load_config

DEFAULT_MODES = ("guided",)
"""Modos incluidos por defecto: las sesiones de referencia son la ruta ideal."""


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se generó, 1 si algo falló.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.study_report",
        description="Genera el informe de resultados de un estudio (HTML).",
    )
    parser.add_argument("--study", type=int, required=True, metavar="ID", help="estudio")
    parser.add_argument("--db", type=Path, help="base (por defecto, database.path)")
    parser.add_argument(
        "--modes", nargs="+", default=list(DEFAULT_MODES), help="modos de sesión (guided, free)"
    )
    parser.add_argument("--versions", nargs="+", help="versiones; por defecto, todas")
    parser.add_argument("--conclusions", type=Path, help="archivo de texto con las conclusiones")
    parser.add_argument("--output", type=Path, help="archivo HTML de salida")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        path = (args.db or config.database.path).resolve()
        db.open_database(path).close()  # valida el esquema antes de abrir de solo lectura
        conclusions = args.conclusions.read_text(encoding="utf-8") if args.conclusions else ""
        with open_data(path) as data:
            inputs = report_inputs.collect(
                data,
                args.study,
                args.modes,
                args.versions,
                source=path.name,
                conclusions=conclusions,
            )
    except (ConfigError, FileNotFoundError, db.SchemaVersionError, LookupError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except sqlite3.Error as error:
        print(f"error: cannot read the database: {error}", file=sys.stderr)
        return 1
    output = args.output or path.parent / "reports" / f"informe-estudio-{args.study}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.render(inputs), encoding="utf-8")
    reading = report.verdict(inputs)
    print(reading.headline)
    print(f"informe: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
