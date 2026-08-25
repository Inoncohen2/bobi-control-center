"""Adapter conformance.

These tests are written against :class:`HomeAssistantAdapter`, not against the
mock. When ``RealHomeAssistantAdapter`` is implemented in Phase 2, add it to
``ADAPTERS`` below and the same suite validates it unchanged.
"""

from __future__ import annotations

import inspect

import pytest

from app.adapters import (
    HomeAssistantAdapter,
    MockHomeAssistantAdapter,
    RealHomeAssistantAdapter,
)
from app.api.deps import build_adapter
from app.config import Settings
from app.models import ProbeResult

#: Phase 2 appends ``RealHomeAssistantAdapter`` here.
ADAPTERS = [MockHomeAssistantAdapter]


@pytest.fixture(params=ADAPTERS)
def any_adapter(request: pytest.FixtureRequest) -> HomeAssistantAdapter:
    return request.param()


def test_every_abstract_method_is_implemented(any_adapter: HomeAssistantAdapter) -> None:
    abstract = {
        name
        for name, member in inspect.getmembers(HomeAssistantAdapter, inspect.isfunction)
        if getattr(member, "__isabstractmethod__", False)
    }
    assert abstract, "the interface should declare abstract methods"
    for name in abstract:
        assert not getattr(getattr(any_adapter, name), "__isabstractmethod__", False)


def test_the_real_adapter_also_satisfies_the_interface() -> None:
    """It must be constructible even though every method raises."""
    adapter = RealHomeAssistantAdapter()
    assert isinstance(adapter, HomeAssistantAdapter)
    assert adapter.name == "real"


@pytest.mark.parametrize(
    "method",
    [
        "get_system_status",
        "get_entities",
        "get_capabilities",
        "get_automations",
        "get_shabbat_config",
        "get_users",
        "get_diagnostics",
        "get_notification_rules",
        "get_tasks",
        "get_calendar_events",
        "get_test_suites",
        "get_audit_entries",
        "get_settings",
    ],
)
async def test_read_methods_return_data(
    any_adapter: HomeAssistantAdapter, method: str
) -> None:
    result = await getattr(any_adapter, method)()
    assert result is not None
    if isinstance(result, list):
        assert result, f"{method} returned an empty list"


async def test_preview_text_returns_a_probe_result_that_cannot_execute(
    any_adapter: HomeAssistantAdapter,
) -> None:
    result = await any_adapter.preview_text("תדליק את אור המטבח")
    assert isinstance(result, ProbeResult)
    assert result.would_execute is False


async def test_writes_are_visible_to_the_next_read(
    any_adapter: HomeAssistantAdapter,
) -> None:
    updated = await any_adapter.set_capability_enabled("vision", True)
    assert updated.enabled is True

    capabilities = {c.id: c for c in await any_adapter.get_capabilities()}
    assert capabilities["vision"].enabled is True


async def test_reads_return_copies_not_internal_state(
    any_adapter: HomeAssistantAdapter,
) -> None:
    """Mutating a returned object must not corrupt the adapter's own data."""
    first = await any_adapter.get_capabilities()
    first[0].name = "TAMPERED"

    second = await any_adapter.get_capabilities()
    assert second[0].name != "TAMPERED"


# --- adapter selection ------------------------------------------------------
def test_mock_is_the_default() -> None:
    adapter = build_adapter(Settings())
    assert isinstance(adapter, MockHomeAssistantAdapter)
    assert adapter.read_only is True


def test_selecting_real_swaps_the_implementation_without_touching_callers() -> None:
    adapter = build_adapter(Settings(adapter="real"))
    assert isinstance(adapter, RealHomeAssistantAdapter)


def test_the_mock_adapter_cannot_reach_the_network() -> None:
    """Structural guarantee, not a runtime one: it imports no HTTP client."""
    source = inspect.getsource(inspect.getmodule(MockHomeAssistantAdapter))
    for forbidden in ("import httpx", "import requests", "import aiohttp", "urlopen"):
        assert forbidden not in source
