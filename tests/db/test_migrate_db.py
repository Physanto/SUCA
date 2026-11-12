"""Migración de bases conservando sesiones, respaldo y atomicidad ante errores."""

from contextlib import closing
from pathlib import Path

import pytest

from scripts.migrate_db import migrate
from shared import db


def old_database(path: Path) -> None:
    """Construye un esquema 7 realista a partir del canónico, con una sesión."""
    with closing(db.connect(path, create=True)) as connection:
        db.create_schema(connection)
        connection.execute("DROP TABLE gaze_attribution")
        connection.execute("DROP TABLE gaze_fixation")
        connection.execute("ALTER TABLE calibration DROP COLUMN css_px_per_cm")
        connection.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
        connection.execute("INSERT INTO study (id,name,system_under_test) VALUES (1,'Test','App')")
        connection.execute("INSERT INTO participant (id) VALUES ('P01')")
        connection.execute(
            "INSERT INTO session (id,study_id,participant_id,version,mode,started_at)"
            " VALUES (1,1,'P01','V0','free',1234)"
        )


def test_migration_preserves_sessions_and_creates_a_readable_backup(tmp_path: Path) -> None:
    path = tmp_path / "real.db"
    old_database(path)
    backup = migrate(path)
    assert backup is not None
    with closing(db.open_database(path)) as connection:
        assert connection.execute("SELECT started_at FROM session").fetchone()[0] == 1234
        assert connection.execute("SELECT COUNT(*) FROM gaze_fixation").fetchone()[0] == 0
        assert "css_px_per_cm" in {
            row["name"] for row in connection.execute("PRAGMA table_info(calibration)")
        }
    with closing(db.connect(backup)) as connection:
        assert db.schema_version(connection) == "7"
        assert connection.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
    assert migrate(path) is None


def test_incompatible_existing_tables_leave_the_old_schema_untouched(tmp_path: Path) -> None:
    path = tmp_path / "real.db"
    old_database(path)
    with closing(db.connect(path)) as connection:
        connection.execute("CREATE TABLE gaze_fixation (wrong INTEGER)")
    with pytest.raises(ValueError, match="incompatible existing object"):
        migrate(path, tmp_path / "backup.db")
    with closing(db.connect(path)) as connection:
        assert db.schema_version(connection) == "7"
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='gaze_attribution'"
        ).fetchone()


def test_refuses_to_replace_an_existing_backup(tmp_path: Path) -> None:
    path, backup = tmp_path / "real.db", tmp_path / "backup.db"
    old_database(path)
    backup.write_bytes(b"keep this backup")
    with pytest.raises(FileExistsError):
        migrate(path, backup)
    assert backup.read_bytes() == b"keep this backup"


def test_refuses_unknown_versions_without_creating_a_backup(tmp_path: Path) -> None:
    path = tmp_path / "old-mock.db"
    old_database(path)
    with closing(db.connect(path)) as connection:
        connection.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    with pytest.raises(ValueError, match="only schema 7 or 8"):
        migrate(path, tmp_path / "backup.db")
    assert not (tmp_path / "backup.db").exists()
