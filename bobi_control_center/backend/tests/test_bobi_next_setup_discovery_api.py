from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.bobi_next.setup_discovery_api as setup_discovery_module
from app.bobi_next.models import DeviceRecord, EntityRecord
from app.bobi_next.setup_discovery_api import create_setup_discovery_router


class FakeSnapshot:
    def __init__(self) -> None:
        self.areas = [{"area_id": "living"}, {"area_id": "bedroom"}]

    def semantic_devices(self):
        light = EntityRecord(
            entity_id="light.private_living",
            domain="light",
            name="Private living light",
            state="on",
            capabilities=frozenset({"power", "brightness"}),
        )
        climate = EntityRecord(
            entity_id="climate.private_bedroom",
            domain="climate",
            name="Private bedroom AC",
            state="cool",
            capabilities=frozenset({"power", "temperature", "hvac_mode"}),
        )
        return (
            DeviceRecord(
                bobi_id="device-1",
                stable_key="device:1",
                name="Private living light",
                entities=(light,),
                capabilities=light.capabilities,
                available=True,
            ),
            DeviceRecord(
                bobi_id="device-2",
                stable_key="device:2",
                name="Private bedroom AC",
                entities=(climate,),
                capabilities=climate.capabilities,
                available=False,
            ),
        )


class FakeDiscoveryClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    async def snapshot(self):
        return FakeSnapshot()

    async def aclose(self):
        self.closed = True


def _client(*, token: str) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_setup_discovery_router(
            api_base_url="http://supervisor/core/api",
            token=token,
            timeout_seconds=1,
        )
    )
    return TestClient(app)


def test_home_scan_requires_app_side_home_assistant_access() -> None:
    response = _client(token="").post("/api/next/setup/home-scan")
    assert response.status_code == 503
    assert response.json()["detail"] == "home_assistant_access_unavailable"


def test_home_scan_returns_only_aggregate_discovery_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        setup_discovery_module,
        "HomeAssistantDiscoveryClient",
        FakeDiscoveryClient,
    )
    response = _client(token="supervisor-token").post("/api/next/setup/home-scan")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "devices": 2,
        "available_devices": 1,
        "entities": 2,
        "areas": 2,
        "capabilities": 4,
        "domains": [
            {"domain": "climate", "entities": 1},
            {"domain": "light", "entities": 1},
        ],
    }
    assert "private_living" not in response.text
    assert "Private living light" not in response.text
    assert "supervisor-token" not in response.text
