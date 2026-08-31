"""The live drift check is a runtime guard, not a copied contract fixture."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_bridge_drift_is_read_only_and_structured(client: TestClient) -> None:
    body = client.get("/api/bobi/manage/bridge-drift").json()

    assert set(body) == {
        "ok",
        "contract_available",
        "contract_version",
        "unknown_resources",
        "unknown_operations",
        "missing_services",
        "writes_enabled",
    }
    assert isinstance(body["unknown_resources"], list)
    assert isinstance(body["unknown_operations"], list)
    assert isinstance(body["missing_services"], list)
    assert body["unknown_resources"] == []
    assert body["unknown_operations"] == []


def test_bridge_drift_does_not_change_management_state(client: TestClient) -> None:
    before = client.get("/api/bobi/manage/contract").json()
    response = client.get("/api/bobi/manage/bridge-drift")
    after = client.get("/api/bobi/manage/contract").json()

    assert response.status_code == 200
    assert before == after
