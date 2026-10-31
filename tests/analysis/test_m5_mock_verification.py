"""Verifica los resultados por tarea y el índice a partir de las capturas del simulador."""

import json
import shutil
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pandas.testing import assert_frame_equal

from analysis import columns
from analysis.loader import SqliteAnalysisRepository
from analysis.parameters import Parameters
from analysis.run import analyze_session
from scripts.generate_mock_data import ground_truth_path
from shared import db


@pytest.mark.parametrize("key", ["reference", "guided_v0", "guided_v1", "guided_v2", "free_v1"])
def test_mock_task_results_and_index_match_truth_with_detected_incidents(
    mock: Any, params: Parameters, tmp_path: Path, key: str
) -> None:
    truth = json.loads(ground_truth_path(mock.path).read_text(encoding="utf-8"))
    expected = next(item for item in truth["sessions"] if item["key"] == key)
    configured = replace(params, version="mock", friction_i_max=truth["friction_i_max"])
    database = tmp_path / "analysis.db"
    shutil.copyfile(mock.path, database)
    tasks = columns.frame(
        "task_result",
        [
            {name: item[name] for name in columns.spec("task_result").columns}
            for item in expected["tasks"]
        ],
    ).sort_values("task_id", ignore_index=True)
    with closing(db.open_database(database)) as connection:
        for table in columns.RESULT_TABLES:
            connection.execute(f"DELETE FROM {table}")
        connection.commit()
        repository = SqliteAnalysisRepository(connection)
        for _ in range(2):
            result = analyze_session(repository, expected["session_id"], configured)
            assert_frame_equal(
                result.task_results.sort_values("task_id", ignore_index=True),
                tasks,
                check_exact=False,
                rtol=0,
                atol=0.101,
                obj=f"{key}: task results",
            )
            if key == "guided_v2":
                card = truth["references"][2]
                assert (
                    result.task_results.set_index("task_id").loc[card["task_id"], "deviation_step"]
                    == card["required_steps"][0]
                )
            names = ", ".join(columns.spec("task_result").columns)
            saved_tasks = columns.frame(
                "task_result",
                [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT {names} FROM task_result WHERE session_id = ? ORDER BY task_id",
                        (expected["session_id"],),
                    )
                ],
            )
            assert_frame_equal(
                saved_tasks,
                result.task_results.sort_values("task_id", ignore_index=True),
                check_exact=True,
            )
            index = expected["usability_index"]
            saved = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usability_index WHERE session_id = ?", (expected["session_id"],)
                )
            ]
            if index is None:
                assert result.usability_index.empty and not saved
            else:
                assert result.usability_index.iloc[0].to_dict() == pytest.approx(index, abs=0.005)
                assert len(saved) == 1
                assert saved[0].pop("session_id") == expected["session_id"]
                assert saved[0].pop("params_version") == "mock"
                assert saved[0] == result.usability_index.iloc[0].to_dict()
