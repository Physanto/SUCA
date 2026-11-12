"""Los reintentos de transporte no duplican una medición de calibración."""

import sqlite3
from pathlib import Path

from server.ingestion import store_calibration
from server.repositories import SqliteRepository


def test_identical_drift_records_are_idempotent_but_new_checks_are_kept(
    connection: sqlite3.Connection, tmp_path: Path,
) -> None:
    writer = SqliteRepository(connection, tmp_path)
    record = {"t": 1791380123456.0, "type": "drift_check", "error_px": 35,
              "error_deg": 1.2, "accepted": True}
    with writer.transaction():
        store_calibration(writer, 1, [record, record])
    with writer.transaction():
        store_calibration(writer, 1, [record, {**record, "t": record["t"] + 3000}])
    assert connection.execute(
        "SELECT COUNT(*) FROM calibration WHERE type='drift_check'"
    ).fetchone()[0] == 2
