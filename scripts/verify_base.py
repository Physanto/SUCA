"""Verificación automática de la base: todo lo que no necesita Chrome.

Ejecuta estas comprobaciones, en orden, y muestra un resumen:

1. estilo de Python (``ruff check`` y ``ruff format --check``), pruebas de
   Python (``pytest``) y pruebas de la extensión (``node --test``);
2. configuración y su copia para la extensión;
3. contratos: cada ejemplo válido o inválido se comporta como dice su nombre;
4. creación de una base y carga del estudio de ejemplo;
5. servidor, con el cliente de pruebas: ``/health``, el token y una sesión con
   un clic de punta a punta;
6. datos simulados: generación determinista y verdad de referencia;
7. acceso a datos del panel sobre la base simulada;
8. pipeline del análisis sobre la base simulada.

Todo se hace en una carpeta temporal: no toca ``data/`` ni la base real.

Uso::

    python -m scripts.verify_base           # todo
    python -m scripts.verify_base --quick   # sin estilo ni pruebas (1)

Lo que necesita Chrome (cargar la extensión, el panel lateral, la prueba
técnica 2) no se verifica aquí.
"""

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.config import ROOT_DIR

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
"""Resultados posibles de una comprobación."""


class Skipped(Exception):
    """La comprobación no se puede hacer en esta computadora (por ejemplo, falta Node)."""


class Failed(Exception):
    """La comprobación no se cumple."""


@dataclass(frozen=True)
class Result:
    """Resultado de una comprobación.

    Attributes:
        name: Nombre de la comprobación.
        status: ``PASS``, ``FAIL`` o ``SKIP``.
        detail: Qué se comprobó o por qué falló.
        seconds: Cuánto tardó.
    """

    name: str
    status: str
    detail: str
    seconds: float


@dataclass
class Workspace:
    """Carpeta temporal de la verificación y lo que van dejando las comprobaciones.

    Attributes:
        folder: Carpeta temporal.
        mock: Base simulada, si ya se generó.
        truth: Su verdad de referencia.
    """

    folder: Path
    mock: Path | None = None
    truth: dict[str, Any] = field(default_factory=dict)


Check = Callable[[Workspace], str]
"""Una comprobación: recibe la carpeta de trabajo y devuelve el detalle de lo comprobado."""


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando en la raíz del repositorio y guarda su salida."""
    return subprocess.run(command, cwd=ROOT_DIR, capture_output=True, text=True, check=False)


def _last_line(output: str) -> str:
    """Última línea no vacía de una salida."""
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def check_style(work: Workspace) -> str:
    """Estilo, documentación y formato de Python con ``ruff``."""
    done = _run([sys.executable, "-m", "ruff", "check", "."])
    if done.returncode != 0:
        raise Failed(_last_line(done.stdout) or _last_line(done.stderr))
    detail = "ruff check: " + (_last_line(done.stdout) or "no issues")
    formatted = _run([sys.executable, "-m", "ruff", "format", "--check", "."])
    if formatted.returncode != 0:
        # Se nombran los archivos para que se sepa qué formatear con ``ruff format .``.
        raise Failed(formatted.stdout.strip() or _last_line(formatted.stderr))
    return detail + "; ruff format: " + (_last_line(formatted.stdout) or "no issues")


def check_python_tests(work: Workspace) -> str:
    """Todas las pruebas de Python con ``pytest``."""
    done = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    summary = _last_line(done.stdout)
    if done.returncode != 0:
        raise Failed(summary)
    return summary


def check_extension_tests(work: Workspace) -> str:
    """Pruebas de la extensión con el ejecutor de Node, si Node está instalado."""
    node = shutil.which("node")
    if node is None:
        raise Skipped("Node.js is not installed")
    # Formato TAP explícito: desde Node 23 el formato por defecto es otro y no trae "# pass N".
    done = _run([node, "--test", "--test-reporter=tap", "extension/tests/**/*.test.js"])
    counts = dict(re.findall(r"^# (pass|fail) (\d+)$", done.stdout, flags=re.MULTILINE))
    if done.returncode != 0:
        raise Failed(f"{counts.get('fail', '?')} failed, {counts.get('pass', '?')} passed")
    return f"{counts.get('pass', '?')} passed"


def check_config(work: Workspace) -> str:
    """La configuración carga y ``config.generated.js`` coincide con ella."""
    from scripts.generate_config import OUTPUT_PATH, render
    from shared.config import load_config

    config = load_config()
    if OUTPUT_PATH.read_text(encoding="utf-8") != render(config):
        raise Failed("extension/config.generated.js is outdated: python -m scripts.generate_config")
    server = f"{config.server.host}:{config.server.port}"
    return f"config valid; extension copy up to date (server {server})"


def check_contracts(work: Workspace) -> str:
    """Cada ejemplo de ``contracts/examples`` cumple o incumple su contrato según su nombre."""
    from shared import contracts

    examples = sorted((contracts.CONTRACTS_DIR / "examples").glob("*.json"))
    wrong = []
    for path in examples:
        kind, expectation = path.name.split(".")[:2]
        errors = contracts.validate(kind, json.loads(path.read_text(encoding="utf-8")))
        if (expectation == "valid") != (not errors):
            wrong.append(path.name)
    if wrong:
        raise Failed(f"examples that behave unexpectedly: {wrong}")
    return f"{len(contracts.kinds())} contracts; {len(examples)} examples behave as named"


def check_database(work: Workspace) -> str:
    """Se crea una base, se carga el estudio de ejemplo y volver a cargarlo no duplica."""
    from scripts.init_db import init_db
    from scripts.load_study import load_study, read_study
    from shared import db

    path = work.folder / "base.db"
    if init_db(path) != "created" or init_db(path) != "unchanged":
        raise Failed("init_db did not create the database once and then leave it unchanged")
    study = read_study(ROOT_DIR / "studies" / "example.yaml")
    with closing(db.open_database(path)) as connection:
        first = load_study(connection, study)
        again = load_study(connection, study)
        tasks = connection.execute("SELECT COUNT(*) FROM task").fetchone()[0]
        version = db.schema_version(connection)
    if first != again or tasks != len(study["tasks"]):
        raise Failed("loading the study twice changed its ids or duplicated tasks")
    return f"schema version {version}; example study with {tasks} tasks; reloading keeps its ids"


def check_server(work: Workspace) -> str:
    """El servidor responde ``/health``, exige el token y guarda un clic de una sesión."""
    with warnings.catch_warnings():
        # El cliente de pruebas avisa de un cambio futuro de su dependencia; no afecta aquí.
        warnings.filterwarnings("ignore", message=".*httpx.*")
        from fastapi.testclient import TestClient

    from scripts.init_db import init_db
    from scripts.load_study import load_study, read_study
    from server.app import create_app
    from shared import contracts, db
    from shared.config import load_config

    path = work.folder / "server.db"
    init_db(path)
    with closing(db.open_database(path)) as connection:
        study = load_study(connection, read_study(ROOT_DIR / "studies" / "example.yaml"))
    config = load_config()
    config = dataclasses.replace(config, database=dataclasses.replace(config.database, path=path))
    headers = {"X-Api-Token": config.server.token}
    request = json.loads(
        (contracts.CONTRACTS_DIR / "examples" / "new-session.valid.json").read_text()
    )
    request["study_id"] = study.study_id
    click = {
        "t": time.time() * 1000,
        "type": "click",
        "x": 120.0,
        "y": 80.0,
        "screen": {"url": "http://127.0.0.1/", "title": "Verificación"},
        "task_id": None,
        "element": {
            "tag": "button",
            "id": "go",
            "role": "button",
            "text": "Ir",
            "selector": "#go",
            "box": {"x": 100, "y": 60, "w": 40, "h": 40},
            "interactive": True,
        },
    }
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*httpx.*")
        with TestClient(create_app(config)) as client:
            health = client.get("/health", headers=headers)
            without_token = client.get("/health")
            session_id = client.post("/sessions", headers=headers, json=request).json()[
                "session_id"
            ]
            batch = {
                "contract_version": contracts.contract_version(),
                "type": "events",
                "records": [click],
            }
            stored = client.post(f"/sessions/{session_id}/batches", headers=headers, json=batch)
            closed = client.post(f"/sessions/{session_id}/close", headers=headers)
    with closing(db.open_database(path)) as connection:
        events = connection.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    if health.status_code != 200 or health.json().get("status") != "ok":
        raise Failed(f"/health answered {health.status_code}")
    if without_token.status_code != 401:
        raise Failed(f"a request without token answered {without_token.status_code}, not 401")
    if stored.status_code != 200 or closed.status_code != 200 or events != 1:
        raise Failed(
            f"batch {stored.status_code}, close {closed.status_code}, {events} events stored"
        )
    return "/health ok; token required (401); session created, click stored, session closed"


def check_mock_data(work: Workspace) -> str:
    """La base simulada se genera igual dos veces y su verdad cubre todos los incidentes."""
    from scripts.generate_mock_data import generate, ground_truth_path
    from shared import contracts

    work.mock = work.folder / "mock.db"
    work.truth = generate(work.mock)
    again = work.folder / "mock-again.db"
    generate(again)
    if ground_truth_path(again).read_bytes() != ground_truth_path(work.mock).read_bytes():
        raise Failed("two generations with the same seed gave different ground truths")
    sessions = work.truth["sessions"]
    types = {incident["type"] for session in sessions for incident in session["incidents"]}
    missing = sorted(set(contracts.enums()["incident_type"]) - types)
    if missing:
        raise Failed(f"incident types without an example in the mock data: {missing}")
    incidents = sum(len(session["incidents"]) for session in sessions)
    return f"{len(sessions)} sessions, {incidents} expected incidents, all types; deterministic"


def check_dashboard(work: Workspace) -> str:
    """El acceso a datos del panel lee la base simulada como dice su verdad de referencia."""
    from dashboard.data import open_data

    if work.mock is None:
        raise Skipped("needs the mock data check")
    sessions = work.truth["sessions"]
    study_id = work.truth["study"]["id"]
    with open_data(work.mock) as data:
        listed = len(data.get_sessions(study_id=study_id))
        incidents = len(data.get_incidents(study_id=study_id))
        results = len(data.get_task_results(study_id))
        indexes = len(data.get_usability_index(study_id))
        confirmed = len(data.get_references(study_id, status="confirmed"))
    expected = (
        len(sessions),
        sum(len(item["incidents"]) for item in sessions),
        sum(len(item["tasks"]) for item in sessions),
        sum(1 for item in sessions if item["usability_index"]),
        len(work.truth["references"]),
    )
    found = (listed, incidents, results, indexes, confirmed)
    if found != expected:
        raise Failed(
            f"read {found}, expected {expected} (sessions, incidents, results, indexes, references)"
        )
    return (
        f"{listed} sessions, {incidents} incidents, {results} task results, "
        f"{indexes} indexes, {confirmed} references"
    )


def check_pipeline(work: Workspace) -> str:
    """El pipeline del análisis corre sin errores sobre cada sesión de la base simulada."""
    from analysis.loader import SqliteAnalysisRepository
    from analysis.parameters import load_parameters
    from analysis.run import STAGES, analyze_session
    from shared import db

    if work.mock is None:
        raise Skipped("needs the mock data check")
    copy = work.folder / "mock-analysis.db"
    shutil.copy(work.mock, copy)
    params = load_parameters()
    with closing(db.open_database(copy)) as connection:
        repository = SqliteAnalysisRepository(connection)
        sessions = repository.list_sessions(work.truth["study"]["id"])
        for session in sessions:
            analyze_session(repository, session.id, params)
    return (
        f"{len(sessions)} sessions through the {len(STAGES)} stages (parameters {params.version})"
    )


CHECKS: tuple[tuple[str, Check, bool], ...] = (
    ("Python style (ruff)", check_style, True),
    ("Python tests (pytest)", check_python_tests, True),
    ("Extension tests (node --test)", check_extension_tests, True),
    ("Configuration", check_config, False),
    ("Contracts", check_contracts, False),
    ("Database and study", check_database, False),
    ("Local server", check_server, False),
    ("Mock data", check_mock_data, False),
    ("Dashboard data access", check_dashboard, False),
    ("Analysis pipeline", check_pipeline, False),
)
"""Comprobaciones en orden: nombre, función y si es una de las suites que salta ``--quick``."""


def run_checks(*, quick: bool = False) -> list[Result]:
    """Ejecuta las comprobaciones en una carpeta temporal.

    Una comprobación que falla no detiene a las demás.

    Args:
        quick: Si es verdadero, salta el estilo y las suites de pruebas.

    Returns:
        Un resultado por comprobación, en orden.
    """
    results = []
    with tempfile.TemporaryDirectory(prefix="suca-verify-", ignore_cleanup_errors=True) as folder:
        work = Workspace(Path(folder))
        for name, check, is_suite in CHECKS:
            started = time.perf_counter()
            if quick and is_suite:
                status, detail = SKIP, "skipped with --quick"
            else:
                try:
                    status, detail = PASS, check(work)
                except Skipped as reason:
                    status, detail = SKIP, str(reason)
                except Exception as error:  # Se informa y se sigue con las demás.
                    status, detail = FAIL, f"{type(error).__name__}: {error}"
            results.append(Result(name, status, detail, time.perf_counter() - started))
    return results


def report(results: list[Result]) -> str:
    """Arma el resumen de la verificación.

    Args:
        results: Resultados de las comprobaciones.

    Returns:
        Una línea por comprobación y el total.
    """
    width = max(len(result.name) for result in results)
    lines = ["SUCA base verification (temporary folder; data/ is not touched)", ""]
    lines += [
        f"  {result.status:<4}  {result.name:<{width}}  {result.detail}  ({result.seconds:.1f} s)"
        for result in results
    ]
    counts = {
        status: sum(1 for result in results if result.status == status)
        for status in (PASS, FAIL, SKIP)
    }
    lines += ["", f"Result: {counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los de la línea de comandos.

    Returns:
        Código de salida: 0 si nada falló, 1 si algo falló.
    """
    parser = argparse.ArgumentParser(
        description="Verifica la base sin Chrome: pruebas, base, servidor, datos simulados, "
        "análisis y panel."
    )
    parser.add_argument("--quick", action="store_true", help="salta el estilo y las pruebas")
    args = parser.parse_args(argv)
    results = run_checks(quick=args.quick)
    print(report(results))
    return 1 if any(result.status == FAIL for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
