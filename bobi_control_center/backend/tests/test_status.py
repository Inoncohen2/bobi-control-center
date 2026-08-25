"""Status, health and settings endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import MASK


def test_health_reports_mock_adapter(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["adapter"] == "mock"


def test_status_shape(client: TestClient) -> None:
    body = client.get("/api/bobi/status").json()

    assert body["adapter"] == "mock"
    assert body["read_only"] is True
    assert {c["id"] for c in body["components"]} == {
        "bobi",
        "whatsapp",
        "ai",
        "home_assistant",
    }
    assert len(body["stats"]) == 5
    assert body["activity"], "the dashboard timeline should not be empty"
    assert body["attention"], "the mock data includes warnings to render"


def test_status_stats_match_the_data(client: TestClient) -> None:
    status = client.get("/api/bobi/status").json()
    automations = client.get("/api/bobi/automations").json()["automations"]
    tasks = client.get("/api/bobi/tasks").json()

    stats = {item["id"]: item["value"] for item in status["stats"]}
    assert stats["automations"] == sum(1 for a in automations if a["enabled"])
    assert stats["tasks"] == len(tasks["open_tasks"])


def test_settings_never_expose_secrets(client: TestClient) -> None:
    body = client.get("/api/bobi/settings").json()
    assert body["read_only"] is True

    secret_fields = [
        field
        for section in body["sections"]
        for field in section["fields"]
        if field["secret"]
    ]
    assert secret_fields, "there should be secret fields to mask"
    for field in secret_fields:
        assert field["value"] == MASK
