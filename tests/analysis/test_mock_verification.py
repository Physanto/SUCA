"""Verificación conjunta de los incidentes y episodios de toda la base simulada."""

import json
import shutil
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import columns
from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import analyze_session
from scripts.generate_mock_data import ground_truth_path
from shared import contracts, db

SESSION_KEYS = ("reference", "guided_v0", "guided_v1", "guided_v2", "free_v1")


def test_verification_covers_every_session_and_contract_type(mock: Any) -> None:
    truth = json.loads(ground_truth_path(mock.path).read_text(encoding="utf-8"))
    sessions = truth["sessions"]
    assert {item["key"] for item in sessions} == set(SESSION_KEYS)
    assert {item["type"] for session in sessions for item in session["incidents"]} == set(
        contracts.enums()["incident_type"]
    )
    assert {item["type"] for session in sessions for item in session["episodes"]} == set(
        contracts.enums()["episode_type"]
    )
    with closing(db.open_database(mock.path)) as connection:
        assert {row[0] for row in connection.execute("SELECT id FROM session")} == {
            item["session_id"] for item in sessions
        }


@pytest.mark.parametrize("key", SESSION_KEYS)
def test_all_mock_incidents_and_episodes_match_the_json(
    mock: Any, params: Parameters, tmp_path: Path, key: str
) -> None:
    truth = json.loads(ground_truth_path(mock.path).read_text(encoding="utf-8"))
    expected = next(item for item in truth["sessions"] if item["key"] == key)
    database = tmp_path / "analysis.db"
    shutil.copyfile(mock.path, database)
    with closing(db.open_database(database)) as connection:
        # El generador precarga resultados esperados: se retiran antes de ejecutar el análisis.
        for table in ("episode", "incident", "task_result", "usability_index"):
            connection.execute(f"DELETE FROM {table}")
        connection.commit()

        result = analyze_session(
            SqliteAnalysisRepository(connection), expected["session_id"], params
        )

        incidents = columns.frame(
            "incident",
            [
                {
                    "type": item["type"],
                    "t": item["t_end"]
                    if item["type"] in ("navigation_loop", "repeated_search")
                    else item["t_start"],
                    "screen": item["screen"],
                    "task_id": item["task_id"],
                    "element": item["element"],
                }
                for item in expected["incidents"]
            ],
        ).sort_values(["t", "type"], ignore_index=True)
        # El simulador redondea los tiempos a décimas de milisegundo.
        assert_frame_equal(
            result.incidents.sort_values(["t", "type"], ignore_index=True),
            incidents,
            check_exact=False,
            rtol=0,
            atol=0.1,
            obj=f"{key}: incidents",
        )
        episodes = columns.frame("episode", expected["episodes"]).sort_values(
            ["t_start", "type"], ignore_index=True
        )
        assert_frame_equal(
            result.episodes.sort_values(["t_start", "type"], ignore_index=True),
            episodes,
            check_exact=True,
            obj=f"{key}: episodes",
        )
        for table, frame, order in (
            ("incident", result.incidents, ["t", "type"]),
            ("episode", result.episodes, ["t_start", "type"]),
        ):
            names = ", ".join(columns.spec(table).columns)
            saved = []
            for row in connection.execute(
                f"SELECT {names} FROM {table} WHERE session_id = ?", (expected["session_id"],)
            ):
                item = dict(row)
                for name in ("element", "metrics"):
                    if name in item and item[name] is not None:
                        item[name] = json.loads(item[name])
                saved.append(item)
            assert_frame_equal(
                columns.frame(table, saved).sort_values(order, ignore_index=True),
                frame.sort_values(order, ignore_index=True),
                check_exact=True,
                obj=f"{key}: saved {table}",
            )
