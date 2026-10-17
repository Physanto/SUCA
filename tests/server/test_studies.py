"""Endpoints de estudios: GET /studies y GET /studies/{id}/tasks."""

import json
import sqlite3

from fastapi.testclient import TestClient


def test_lists_studies(client: TestClient) -> None:
    response = client.get("/studies")

    assert response.status_code == 200
    [study] = response.json()
    assert study["id"] == 1
    assert study["name"] == "Tienda de ejemplo"
    assert set(study) == {"id", "name", "system_under_test", "description"}


def test_lists_tasks_in_order_with_their_confirmed_references(
    client: TestClient, connection: sqlite3.Connection
) -> None:
    end_condition = {"type": "visible_text", "text": "Pedido confirmado"}
    connection.execute(
        "INSERT INTO reference (task_id, steps, candidates, end_condition, required_steps, status) "
        "VALUES (3, '[]', '[]', ?, '[]', 'confirmed')",
        (json.dumps(end_condition),),
    )
    connection.execute(
        "INSERT INTO reference (task_id, steps, candidates, required_steps, status) "
        "VALUES (3, '[]', '[]', '[]', 'draft')"
    )

    tasks = client.get("/studies/1/tasks").json()

    assert [task["position"] for task in tasks] == [1, 2, 3, 4]
    assert set(tasks[0]) == {"id", "position", "instruction", "references"}
    assert tasks[0]["references"] == []
    assert tasks[2]["references"] == [{"id": 1, "end_condition": end_condition}]


def test_tasks_of_an_unknown_study_are_not_found(client: TestClient) -> None:
    response = client.get("/studies/99/tasks")

    assert response.status_code == 404
    assert response.json() == {"detail": "study 99 not found"}
