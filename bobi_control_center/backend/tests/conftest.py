"""Shared fixtures.

No test requires a live Home Assistant: every bridge call is served by a
`httpx.MockTransport`, so CI never touches a real installation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters import MockHomeAssistantAdapter, RealHomeAssistantAdapter
from app.config import Settings
from app.main import create_app

TEST_BASE_URL = "http://supervisor.test/core/api"
TEST_TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def mock_settings(tmp_path) -> Settings:
    """Mock adapter, and a `data` directory that belongs to this test.

    The management trail is written to `data_dir`, so a shared one would let
    one test read another's audit lines — and would leave a `data/` folder in
    the working tree after every run.
    """
    return Settings(adapter="mock", data_dir=tmp_path / "data")


@pytest.fixture
def client(mock_settings: Settings) -> TestClient:
    """A client backed by the mock adapter."""
    return TestClient(create_app(mock_settings))


@pytest.fixture
def adapter() -> MockHomeAssistantAdapter:
    return MockHomeAssistantAdapter()


@pytest.fixture
def real_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings that select the real adapter, with a fake token."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", TEST_TOKEN)
    return Settings(adapter="real", ha_base_url=TEST_BASE_URL)


@pytest.fixture
def make_real_adapter(
    real_settings: Settings,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], RealHomeAssistantAdapter]:
    """Build a real adapter whose transport is a caller-supplied handler."""

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> RealHomeAssistantAdapter:
        transport = httpx.MockTransport(handler)
        return RealHomeAssistantAdapter(
            real_settings, client=httpx.AsyncClient(transport=transport)
        )

    return factory


def json_response(payload: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


@pytest.fixture
def recorded_requests() -> list[httpx.Request]:
    """Collects requests so tests can assert on URL, body and headers."""
    return []
