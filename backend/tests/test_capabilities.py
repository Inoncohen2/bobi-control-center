"""Capability listing, detail and toggling."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_capabilities(client: TestClient) -> None:
    capabilities = client.get("/api/bobi/capabilities").json()
    assert len(capabilities) >= 10

    by_id = {c["id"]: c for c in capabilities}
    assert "shabbat" in by_id
    assert by_id["shabbat"]["name"] == "שעון שבת"
    assert by_id["cameras"]["warning"], "the degraded capability carries a warning"


def test_capability_detail_includes_settings(client: TestClient) -> None:
    capability = client.get("/api/bobi/capabilities/smart_notifications").json()
    keys = {setting["key"] for setting in capability["settings"]}
    assert {"recipient", "active_hours"} <= keys


def test_toggle_capability_persists_and_is_audited(client: TestClient) -> None:
    before = client.get("/api/bobi/capabilities/vision").json()
    assert before["enabled"] is False

    toggled = client.post(
        "/api/bobi/capabilities/vision/toggle", json={"enabled": True}
    ).json()
    assert toggled["enabled"] is True
    assert toggled["state_label"] == "פעיל"

    # The change is visible to a subsequent read.
    assert client.get("/api/bobi/capabilities/vision").json()["enabled"] is True

    audit = client.get("/api/bobi/audit").json()["entries"]
    latest = audit[0]
    assert latest["resource_type"] == "capability"
    assert latest["resource_id"] == "vision"
    assert latest["operation"] == "toggle"


def test_toggle_unknown_capability_is_a_structured_404(client: TestClient) -> None:
    response = client.post("/api/bobi/capabilities/nope/toggle", json={"enabled": True})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
