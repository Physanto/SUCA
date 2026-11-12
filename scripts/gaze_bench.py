"""Banco de pruebas de la mirada: mide en grados la mirada de una sesión.

Usa los cuadros (``gaze_feature``) y los puntos que se pidió mirar
(``gaze_target``) de una sesión ya capturada, sin volver a llamar al
participante. Muestra el error en vivo y el del modelo geométrico reajustado
fuera de línea, por fase, región de la pantalla, cambio de postura y a lo largo
del tiempo, más la vuelta del teclado, la precisión y los estados de la mirada.

Protocolo sugerido para una sesión de desarrollo (con consentimiento, ~10 min):
calibración inicial; luego pedir "Comprobar la mirada" desde el panel después
de cada cambio: leer un texto, escribir mirando el teclado, mirar a un costado,
inclinarse hacia atrás, acercarse; y la calibración final. Con
``camera.drift_correction`` en ``false`` las comprobaciones solo miden.

Uso::

    python -m scripts.gaze_bench --session 17
    python -m scripts.gaze_bench --session 17 --db data/otra.db --json informe.json
"""

import argparse
import json
import sys
from contextlib import closing
from pathlib import Path

from analysis.gaze import GazeSettings
from analysis.gaze.bench import BenchReport, evaluate, render
from analysis.loader import NotFoundError, SqliteAnalysisRepository
from analysis.parameters import ParametersError, load_parameters
from shared import db
from shared.config import ConfigError, load_config


def report_to_json(report: BenchReport) -> dict:
    """Pasa el informe a un diccionario que se puede guardar como JSON.

    Args:
        report: Informe del banco de pruebas.

    Returns:
        Resumen y una lista de filas por tabla.
    """
    tables = ("by_phase", "by_region", "by_pose", "over_time", "states")
    return {
        "summary": report.summary,
        **{name: json.loads(getattr(report, name).to_json(orient="records")) for name in tables},
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si se midió, 1 si algo falló.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.gaze_bench",
        description="Mide en grados la mirada de una sesión capturada.",
    )
    parser.add_argument("--session", type=int, required=True, metavar="ID", help="sesión")
    parser.add_argument(
        "--db", type=Path, help="ruta de la base (por defecto, database.path de la configuración)"
    )
    parser.add_argument("--json", type=Path, metavar="ARCHIVO", help="guarda el informe en JSON")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        settings = GazeSettings.from_config(config.camera, load_parameters().gaze)
        connection = db.open_database(args.db or config.database.path)
    except (ConfigError, ParametersError, FileNotFoundError, db.SchemaVersionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    with closing(connection):
        try:
            inputs = SqliteAnalysisRepository(connection).load_gaze_inputs(args.session)
        except NotFoundError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    if inputs.features.empty:
        print(
            f"error: session {args.session} has no gaze features "
            "(camera.record_gaze_features was off or the camera did not run)",
            file=sys.stderr,
        )
        return 1
    settings = settings.for_session(inputs.calibrations)
    report = evaluate(inputs.features, inputs.targets, inputs.calibrations, settings)
    print(render(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(report_to_json(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
