"""El esquema tiene todas las tablas y reglas de la base de datos del sistema."""

import re
import sqlite3

import pytest

from server.ingestion import GAZE_FEATURE_COLUMNS
from shared import db

EXPECTED_COLUMNS = {
    "study": ["id", "name", "system_under_test", "description", "recorded_fields"],
    "task": ["id", "study_id", "position", "instruction"],
    "participant": ["id", "age", "digital_experience", "wears_glasses"],
    "session": [
        "id",
        "study_id",
        "participant_id",
        "version",
        "mode",
        "started_at",
        "ended_at",
        "screen_info",
        "calibration_error_start",
        "calibration_error_end",
    ],
    "event": ["id", "session_id", "t", "type", "x", "y", "screen", "task_id", "element", "data"],
    "gaze_sample": [
        "session_id",
        "t",
        "x",
        "y",
        "scroll_x",
        "scroll_y",
        "element_selector",
        "zone",
        "valid",
        "state",
        "confidence",
    ],
    "face_sample": ["session_id", "t", "values", "head_yaw", "head_pitch", "face_detected"],
    "calibration": [
        "session_id",
        "t",
        "type",
        "error_px",
        "error_deg",
        "accepted",
        "viewing_distance_cm",
        "css_px_per_cm",
        "camera_delay_ms",
        "precision_deg",
        "return_error_deg",
        "estimator",
        "corrected",
        "correction_x_px",
        "correction_y_px",
    ],
    "gaze_feature": ["session_id", *GAZE_FEATURE_COLUMNS],
    "gaze_target": [
        "session_id",
        "t",
        "t_end",
        "calibration_type",
        "phase",
        "group",
        "viewport_width",
        "viewport_height",
        "points",
    ],
    "page_layout": [
        "session_id",
        "t",
        "screen",
        "viewport_width",
        "viewport_height",
        "scroll_x",
        "scroll_y",
        "regions",
        "elements",
        "truncated",
    ],
    "session_task": ["session_id", "task_id", "t_start", "t_end", "ended_by"],
    "sus_response": ["session_id", "answers", "score"],
    "episode": ["session_id", "type", "t_start", "t_end", "screen", "outcome", "metrics"],
    "incident": ["session_id", "type", "t", "screen", "task_id", "element"],
    "task_result": [
        "session_id",
        "task_id",
        "success",
        "duration_ms",
        "steps",
        "deviation_step",
        "off_path_ms",
    ],
    "usability_index": [
        "session_id",
        "effectiveness",
        "time_efficiency",
        "path_efficiency",
        "friction",
        "bui",
        "params_version",
    ],
    "gaze_refined": [
        "session_id",
        "t",
        "x",
        "y",
        "scroll_x",
        "scroll_y",
        "state",
        "confidence",
        "valid",
        "zone",
        "element_selector",
        "fixation",
    ],
    "gaze_quality": [
        "session_id",
        "method",
        "fit_scope",
        "frames",
        "check_samples",
        "camera_delay_ms",
        "live_error_deg",
        "refined_error_deg",
        "drift_corrected",
        "residual_lambda",
        "noise_px",
        "fixations",
    ],
    "gaze_fixation": [
        "session_id",
        "fixation",
        "t_start",
        "t_end",
        "x",
        "y",
        "scroll_x",
        "scroll_y",
        "screen",
        "sigma_px",
        "element_selector",
        "element_p",
        "resolved_selector",
        "resolved_p",
        "ambiguous",
        "unassigned_p",
        "attention_selector",
        "attention_p",
        "long_stare",
    ],
    "gaze_attribution": [
        "session_id",
        "fixation",
        "selector",
        "tag",
        "interactive",
        "p_gaze",
        "p_attention",
    ],
    "reference": [
        "id",
        "task_id",
        "source_session_id",
        "steps",
        "candidates",
        "end_condition",
        "required_steps",
        "status",
        "duration_ms",
    ],
    "screen_capture": ["id", "study_id", "screen", "file_path", "t"],
    "session_frame": ["id", "session_id", "t", "file_path"],
    "meta": ["key", "value"],
}

HIGH_VOLUME_TABLES = [
    "event",
    "gaze_sample",
    "face_sample",
    "calibration",
    "gaze_feature",
    "gaze_target",
    "page_layout",
    "gaze_refined",
    "incident",
]


def columns(connection: sqlite3.Connection, table: str) -> list[str]:
    """Columnas de una tabla, en orden."""
    return [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]


def test_all_tables_exist(connection: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert tables == set(EXPECTED_COLUMNS)


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_table_has_expected_columns(connection: sqlite3.Connection, table: str) -> None:
    assert columns(connection, table) == EXPECTED_COLUMNS[table]


@pytest.mark.parametrize("table", HIGH_VOLUME_TABLES)
def test_high_volume_tables_are_indexed_by_session_and_time(
    connection: sqlite3.Connection, table: str
) -> None:
    indexed = [
        [info["name"] for info in connection.execute(f"PRAGMA index_info({index['name']})")]
        for index in connection.execute(f"PRAGMA index_list({table})")
    ]

    assert ["session_id", "t"] in indexed


def test_schema_version_is_stored_in_meta(connection: sqlite3.Connection) -> None:
    assert db.schema_version(connection) == db.expected_schema_version()


def test_schema_has_no_enum_checks() -> None:
    """Los valores de enumeraciones se validan con los contratos, no en SQL."""
    schema = db.SCHEMA_PATH.read_text(encoding="utf-8")

    assert re.search(r"\bCHECK\s*\(", schema, flags=re.IGNORECASE) is None


def test_foreign_keys_are_enforced(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO event (session_id, t, type, screen) VALUES (999, 1, 'click', '{}')"
        )


def test_deleting_a_participant_removes_all_their_data(
    connection: sqlite3.Connection, session_id: int
) -> None:
    """Un participante que se retira se borra con todas sus sesiones, datos y resultados."""
    connection.execute(
        "INSERT INTO event (session_id, t, type, screen) VALUES (?, 1, 'click', '{}')",
        (session_id,),
    )
    connection.execute(
        "INSERT INTO gaze_sample (session_id, t, valid) VALUES (?, 1, 0)", (session_id,)
    )
    connection.execute(
        "INSERT INTO incident (session_id, type, t) VALUES (?, 'dead_click', 1)", (session_id,)
    )

    connection.execute("DELETE FROM participant WHERE id = 'P01'")

    for table in ("session", "event", "gaze_sample", "incident"):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_task_with_reference_cannot_be_deleted(
    connection: sqlite3.Connection, session_id: int
) -> None:
    connection.execute(
        "INSERT INTO reference (task_id, steps, candidates, required_steps, status) "
        "VALUES (1, '[]', '[]', '[]', 'draft')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM task WHERE id = 1")


def test_face_values_column_works_when_quoted(
    connection: sqlite3.Connection, session_id: int
) -> None:
    """La columna "values" es palabra reservada de SQL; entre comillas dobles funciona."""
    connection.execute(
        'INSERT INTO face_sample (session_id, t, "values", face_detected) VALUES (?, 1, ?, 1)',
        (session_id, '{"brow_inner_up": 0.1}'),
    )

    row = connection.execute('SELECT "values" FROM face_sample').fetchone()

    assert row["values"] == '{"brow_inner_up": 0.1}'
