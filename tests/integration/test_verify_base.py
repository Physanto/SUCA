"""Prueba de ``scripts.verify_base``: la verificación rápida de la base pasa.

Se usa ``--quick`` porque la verificación completa vuelve a ejecutar ``pytest``.
"""

import pytest

from scripts.verify_base import CHECKS, FAIL, PASS, SKIP, main, report, run_checks


def test_the_quick_verification_passes(capsys: pytest.CaptureFixture) -> None:
    code = main(["--quick"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Result: 7 passed, 0 failed, 3 skipped" in output
    for name, _, _ in CHECKS:
        assert name in output


def test_a_failing_check_is_reported_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(work: object) -> str:
        raise RuntimeError("no database")

    checks = [
        (name, broken if name == "Contracts" else check, suite) for name, check, suite in CHECKS
    ]
    monkeypatch.setattr("scripts.verify_base.CHECKS", tuple(checks))

    results = run_checks(quick=True)

    statuses = {result.name: result.status for result in results}
    assert statuses["Contracts"] == FAIL
    assert statuses["Analysis pipeline"] == PASS
    assert statuses["Python tests (pytest)"] == SKIP
    assert "RuntimeError: no database" in report(results)
