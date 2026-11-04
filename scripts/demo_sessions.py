"""Genera sesiones de demostración reales con Chrome automático y las analiza.

Recorre de punta a punta lo que hace el sistema, sin personas:

1. Carga el estudio ``studies/demo.yaml`` (las 4 tareas de la tienda, en un
   estudio aparte para no mezclarse con las sesiones de personas).
2. Graba la referencia de las 4 tareas en modo referencia, con una captura de
   cada pantalla (fondo de los mapas de calor y de la reproducción).
3. Analiza la referencia y confirma la condición final de cada tarea.
4. Hace una sesión guiada en cada versión (V0, V1 y V2), con SUS. En V1 y V2 la
   persona automática insiste en lo que no responde, como lo haría una persona.
5. Analiza las sesiones guiadas: incidentes, resultados por tarea e índice.

Las sesiones salen de la captura real de la extensión (con el panel real), pero
**sin cámara**: Chrome sin interfaz no tiene webcam, así que no hay mirada ni
rostro. La mirada se prueba con una sesión de una persona.

Necesita Chrome y Node. Usa el servidor local si ya está corriendo; si no,
levanta uno con la base de la configuración (o la de ``--db``). La app de prueba
se sirve en un puerto libre.

Uso::

    python -m scripts.demo_sessions            # base de config/shared.json
    python -m scripts.demo_sessions --db otra.db
"""

import argparse
import dataclasses
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import Parameters, load_parameters
from analysis.run import analyze_session
from dashboard.data import open_data
from scripts.init_db import init_db
from scripts.load_study import load_study, read_study
from scripts.serve_test_app import create_server
from scripts.simulation.scenarios import MOCK_FRICTION_I_MAX
from shared import db
from shared.config import ROOT_DIR, load_config

#: Estudio de las sesiones de demostración.
STUDY_FILE = ROOT_DIR / "studies" / "demo.yaml"

#: Guion que maneja Chrome.
DRIVER = ROOT_DIR / "tests" / "integration" / "browser" / "guided-session.mjs"

#: Tiempo máximo de cada corrida de Chrome, en segundos.
RUN_TIMEOUT_S = 400

#: Sesiones guiadas: versión, participante y si insiste en lo que no responde.
GUIDED_RUNS = (("V0", "DEMO-V0", False), ("V1", "DEMO-V1", True), ("V2", "DEMO-V2", True))

#: Condición final de cada tarea, por posición: los estados finales del README de la
#: app de prueba. Las candidatas del análisis no siempre los traen (por ejemplo, en la
#: tarea 4 solo proponen llegar a la página, antes de guardar), así que se fijan aquí.
END_CONDITIONS: dict[int, dict[str, str]] = {
    1: {"type": "url_pattern", "pattern": "/product/{id}"},
    2: {"type": "visible_text", "text": "Audífonos inalámbricos SoundMax × 2"},
    3: {"type": "visible_text", "text": "Pedido confirmado"},
    4: {"type": "visible_text", "text": "Dirección actualizada"},
}


def _port_is_free(host: str, port: int) -> bool:
    """Indica si nadie escucha en el puerto."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        return probe.connect_ex((host, port)) != 0


def _start_server(path: Path) -> Any:
    """Levanta el servidor local con la base dada, en un hilo. Devuelve el servidor."""
    import uvicorn

    from server.app import create_app

    config = load_config()
    config = dataclasses.replace(config, database=dataclasses.replace(config.database, path=path))
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host=config.server.host,
            port=config.server.port,
            log_level="warning",
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the local server did not start")
        time.sleep(0.05)
    return server


def _drive(app_url: str, study: str, *args: str) -> dict[str, Any]:
    """Corre el guion de Chrome y devuelve su resumen; falla si el guion falló."""
    command = [shutil.which("node") or "node", str(DRIVER), "--app-url", app_url, "--study", study]
    result = subprocess.run(
        [*command, *args], capture_output=True, text=True, timeout=RUN_TIMEOUT_S, cwd=ROOT_DIR
    )
    if result.returncode != 0:
        raise RuntimeError(f"Chrome run failed:\n{result.stderr[-2000:]}")
    summary = json.loads(result.stdout)
    if summary["error"]:
        raise RuntimeError(f"Chrome run failed:\n{summary['error']}")
    return summary


def _newest_session(path: Path, participant: str) -> int:
    """Id de la última sesión de un participante."""
    with closing(db.open_database(path)) as connection:
        row = connection.execute(
            "SELECT MAX(id) FROM session WHERE participant_id = ?", (participant,)
        ).fetchone()
    if row[0] is None:
        raise RuntimeError(f"no session was stored for {participant}")
    return int(row[0])


def _wait_closed(path: Path, session_id: int, timeout_s: float = 15) -> None:
    """Espera a que el worker cierre la sesión en el servidor."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with closing(db.open_database(path)) as connection:
            (ended,) = connection.execute(
                "SELECT ended_at FROM session WHERE id = ?", (session_id,)
            ).fetchone()
        if ended is not None:
            return
        time.sleep(0.3)
    raise RuntimeError(f"session {session_id} was not closed")


def demo_parameters() -> Parameters:
    """Parámetros del análisis para la demostración.

    Mientras el piloto no fije ``friction_i_max`` (en ``parameters.yaml`` es
    ``null``), el índice no se calcula. Para la demostración se usa el mismo valor
    provisional que los datos simulados, y la versión de los parámetros lo dice.

    Returns:
        Los parámetros de ``parameters.yaml``, con ``friction_i_max`` provisional si falta.
    """
    params = load_parameters()
    if params.friction_i_max is not None:
        return params
    return dataclasses.replace(
        params, friction_i_max=MOCK_FRICTION_I_MAX, version=f"{params.version}+demo-i_max"
    )


def _analyze(path: Path, session_id: int) -> str:
    """Analiza una sesión y guarda sus resultados; devuelve el resumen del análisis."""
    from analysis.run import summary

    with closing(db.open_database(path)) as connection:
        repository = SqliteAnalysisRepository(connection)
        results = analyze_session(repository, session_id, demo_parameters())
    return summary(results)


def _confirm_references(path: Path, study_id: int) -> list[str]:
    """Confirma cada referencia del estudio con la condición final de su tarea."""
    confirmed = []
    with open_data(path) as data:
        for row in data.get_references(study_id).itertuples():
            condition = END_CONDITIONS[int(row.position)]
            data.confirm_reference(int(row.reference_id), condition, [])
            confirmed.append(f"task {row.position}: {json.dumps(condition, ensure_ascii=False)}")
    return confirmed


def _clear_demo_sessions(path: Path, study_id: int) -> int:
    """Borra las sesiones y referencias anteriores del estudio de demostración.

    Solo toca ese estudio: las sesiones de personas están en otros. Borrar una
    sesión borra en cascada sus datos y resultados.
    """
    with closing(db.open_database(path)) as connection, db.transaction(connection):
        connection.execute(
            "DELETE FROM reference WHERE task_id IN (SELECT id FROM task WHERE study_id = ?)",
            (study_id,),
        )
        connection.execute("DELETE FROM screen_capture WHERE study_id = ?", (study_id,))
        deleted = connection.execute("DELETE FROM session WHERE study_id = ?", (study_id,)).rowcount
    return deleted


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si todo salió bien.
    """
    parser = argparse.ArgumentParser(description="Genera y analiza sesiones de demostración.")
    parser.add_argument(
        "--db", type=Path, help="base (por defecto, database.path de la configuración)"
    )
    args = parser.parse_args(argv)
    config = load_config()
    path = args.db or config.database.path
    if shutil.which("node") is None:
        print("error: Node is not installed", file=sys.stderr)
        return 1

    init_db(path)
    with closing(db.open_database(path)) as connection:
        study = read_study(STUDY_FILE)
        study_id = load_study(connection, study).study_id
    print(f"study {study_id}: {study['name']}")
    deleted = _clear_demo_sessions(path, study_id)
    if deleted:
        print(f"deleted {deleted} earlier demo session(s)")

    server = None
    if _port_is_free(config.server.host, config.server.port):
        server = _start_server(path)
        print(f"local server started on port {config.server.port} with {path}")
    elif args.db is not None:
        print("error: a local server is already running; stop it to use --db", file=sys.stderr)
        return 1
    else:
        print("using the local server that is already running")
    app = create_server(0)
    threading.Thread(target=app.serve_forever, daemon=True).start()
    app_url = f"http://127.0.0.1:{app.server_address[1]}"
    try:
        print("recording the reference of the 4 tasks, with a capture of each screen…")
        _drive(app_url, study["name"], "--mode", "reference", "--participant", "DEMO-REF",
               "--version", "V0", "--complete-all")  # fmt: skip
        reference_session = _newest_session(path, "DEMO-REF")
        _wait_closed(path, reference_session)
        print(_analyze(path, reference_session))
        for line in _confirm_references(path, study_id):
            print(f"  confirmed {line}")
        for version, participant, frustrated in GUIDED_RUNS:
            print(f"guided session in {version}…")
            extra = ["--frustrated"] if frustrated else []
            _drive(app_url, study["name"], "--participant", participant, "--version", version,
                   "--complete-all", "--no-browse", *extra)  # fmt: skip
            session_id = _newest_session(path, participant)
            _wait_closed(path, session_id)
            print(_analyze(path, session_id))
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        app.shutdown()
        if server is not None:
            server.should_exit = True
    print(f"done: open the dashboard and choose the study «{study['name']}»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
