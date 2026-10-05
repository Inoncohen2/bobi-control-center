from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_next_setup_api_is_disabled_by_default(tmp_path):
    app = create_app(Settings(adapter="mock", data_dir=tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/next/setup/status")
        assert client.get("/api/next/setup/archive").status_code == 404
        assert client.post("/api/next/setup/archive/check").status_code == 404
        assert client.put("/api/next/setup/archive", json={"mode": "local"}).status_code == 404
        assert client.post("/api/next/setup/integrations", json={}).status_code == 404
    assert response.status_code == 404


def test_next_setup_api_can_be_enabled_without_touching_production_routes(tmp_path):
    app = create_app(
        Settings(adapter="mock", data_dir=tmp_path, next_setup_enabled=True)
    )
    with TestClient(app) as client:
        response = client.get("/api/next/setup/status")
        assert client.get("/api/next/setup/archive").json()["mode"] == "local"
        assert client.get("/api/next/setup/integrations").json() == []
    assert response.status_code == 200
    body = response.json()
    assert body["setup"]["completed"] is False
    assert body["setup"]["ready"] is False
    assert body["setup"]["missing_steps"] == [
        "messaging_provider",
        "user",
        "user_identity",
        "ai_provider",
    ]
