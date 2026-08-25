"""Shared fixtures.

Each test gets a freshly built app, so the in-memory mock adapter never carries
state between tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters import MockHomeAssistantAdapter
from app.config import Settings
from app.main import create_app
from app.services import BobiService, PreviewStore


@pytest.fixture
def settings() -> Settings:
    return Settings(adapter="mock")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def adapter() -> MockHomeAssistantAdapter:
    return MockHomeAssistantAdapter()


@pytest.fixture
def service(adapter: MockHomeAssistantAdapter) -> BobiService:
    return BobiService(adapter, PreviewStore())
