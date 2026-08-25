"""The real adapter: service calls, response unwrapping, errors and safety."""

from __future__ import annotations

import httpx
import pytest

from app.adapters import MockHomeAssistantAdapter, RealHomeAssistantAdapter
from app.adapters.real import ALLOWED_SERVICES, READ_SERVICES, extract_service_response
from app.api.deps import build_adapter
from app.config import Settings
from app.errors import BobiError
from tests.conftest import TEST_TOKEN, json_response

STATUS_PAYLOAD = {"ok": True, "version": "1.2.3", "components": [], "counts": {}}


# --- the service call -------------------------------------------------------
async def test_calls_the_bridge_script_with_the_supervisor_token(
    make_real_adapter, recorded_requests
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return json_response({"service_response": STATUS_PAYLOAD})

    adapter = make_real_adapter(handler)
    status = await adapter.get_status()
    await adapter.aclose()

    assert status.version == "1.2.3"

    request = recorded_requests[0]
    assert request.method == "POST"
    assert request.url.path == "/core/api/services/script/bobi_cc_status"
    # `?return_response` is what makes a script hand data back.
    assert "return_response" in request.url.params
    assert request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"


async def test_devices_sends_scope_and_include_unavailable(
    make_real_adapter, recorded_requests
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return json_response({"service_response": {"devices": [], "count": 0}})

    adapter = make_real_adapter(handler)
    await adapter.get_devices(scope="climate", include_unavailable=False)
    await adapter.aclose()

    import json as jsonlib

    body = jsonlib.loads(recorded_requests[0].content)
    assert body == {"scope": "climate", "include_unavailable": False}


async def test_probe_sends_the_text_and_forces_probe_only(
    make_real_adapter, recorded_requests
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        # Even a bridge that wrongly claimed execution must not change this.
        return json_response(
            {"service_response": {"handled": True, "skill": "x", "would_execute": True}}
        )

    adapter = make_real_adapter(handler)
    result = await adapter.probe("כבה מזגן הורים")
    await adapter.aclose()

    import json as jsonlib

    assert jsonlib.loads(recorded_requests[0].content) == {"text": "כבה מזגן הורים"}
    assert recorded_requests[0].url.path.endswith("/script/bobi_cc_probe")
    assert result.would_execute is False
    assert result.probe_only is True


# --- service_response extraction -------------------------------------------
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # The current Home Assistant shape.
        ({"service_response": {"ok": True}}, {"ok": True}),
        # A bare object.
        ({"ok": True}, {"ok": True}),
        # Wrapped in a single-element list.
        ([{"service_response": {"ok": True}}], {"ok": True}),
        ([{"ok": True}], {"ok": True}),
        # Nested list inside service_response.
        ({"service_response": [{"ok": True}]}, {"ok": True}),
        # An alternative "response" key.
        ({"response": {"ok": True}}, {"ok": True}),
        # Empty results.
        ([], None),
        # A genuinely multi-element list passes through untouched.
        ([{"a": 1}, {"b": 2}], [{"a": 1}, {"b": 2}]),
    ],
)
def test_extract_service_response_handles_every_known_shape(payload, expected) -> None:
    assert extract_service_response(payload) == expected


async def test_unwraps_a_bare_object_response(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response(STATUS_PAYLOAD))
    status = await adapter.get_status()
    await adapter.aclose()
    assert status.version == "1.2.3"


async def test_an_empty_response_yields_an_empty_model(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response(None))
    status = await adapter.get_status()
    await adapter.aclose()
    assert status.components == []


# --- errors -----------------------------------------------------------------
async def test_missing_bridge_script_is_reported_clearly(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response({"message": "not found"}, 404))

    with pytest.raises(BobiError) as exc:
        await adapter.get_status()
    await adapter.aclose()

    assert exc.value.code == "bridge_service_missing"
    assert "bobi_cc_status" in exc.value.message
    # The user-facing message must not be a traceback.
    assert "Traceback" not in exc.value.message


async def test_unauthorized_is_reported_without_leaking_the_token(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response({"message": "denied"}, 401))

    with pytest.raises(BobiError) as exc:
        await adapter.get_status()
    await adapter.aclose()

    assert exc.value.code == "ha_unauthorized"
    assert TEST_TOKEN not in exc.value.message
    assert TEST_TOKEN not in str(exc.value.details)


async def test_server_error_becomes_a_structured_error(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response({"message": "boom"}, 500))

    with pytest.raises(BobiError) as exc:
        await adapter.get_status()
    await adapter.aclose()

    assert exc.value.code == "ha_error"
    assert exc.value.details["status"] == 500


async def test_a_timeout_is_reported_not_swallowed(make_real_adapter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    adapter = make_real_adapter(handler)
    with pytest.raises(BobiError) as exc:
        await adapter.get_status()
    await adapter.aclose()

    assert exc.value.code == "upstream_unavailable"


async def test_non_json_response_is_reported(make_real_adapter) -> None:
    adapter = make_real_adapter(
        lambda request: httpx.Response(200, content=b"<html>nope</html>")
    )
    with pytest.raises(BobiError) as exc:
        await adapter.get_status()
    await adapter.aclose()

    assert exc.value.code == "upstream_unavailable"


async def test_unexpected_shape_is_reported(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response("just a string"))
    with pytest.raises(BobiError) as exc:
        await adapter.get_status()
    await adapter.aclose()

    assert exc.value.code == "bridge_bad_shape"


async def test_connection_info_reports_a_failure_without_raising(make_real_adapter) -> None:
    adapter = make_real_adapter(lambda request: json_response({}, 500))
    info = await adapter.connection_info()
    await adapter.aclose()

    assert info.connected is False
    assert info.writes_enabled is False


# --- safety -----------------------------------------------------------------
async def test_only_the_bridge_services_may_be_called(make_real_adapter) -> None:
    """A non-bridge script is refused before any request is made."""
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(str(request.url))
        return json_response({})

    adapter = make_real_adapter(handler)
    with pytest.raises(BobiError) as exc:
        await adapter.call_service("script", "turn_everything_off")
    await adapter.aclose()

    assert exc.value.code == "service_not_allowed"
    assert called == [], "no HTTP request should have been attempted"


def test_the_read_services_are_exactly_the_nine_bridge_scripts() -> None:
    """Phase 3A added management services beside these, and changed none of them."""
    assert {
        "bobi_cc_status",
        "bobi_cc_devices",
        "bobi_cc_capabilities",
        "bobi_cc_users",
        "bobi_cc_shabbat",
        "bobi_cc_rules",
        "bobi_cc_tasks",
        "bobi_cc_diagnostics",
        "bobi_cc_probe",
    } == READ_SERVICES
    assert READ_SERVICES <= ALLOWED_SERVICES


def test_neither_adapter_exposes_a_write_method() -> None:
    """Read-only is structural: the interface has no write to implement."""
    forbidden = ("turn_on", "turn_off", "set_", "save_", "delete_", "create_", "update_")
    for cls in (RealHomeAssistantAdapter, MockHomeAssistantAdapter):
        for name in dir(cls):
            if name.startswith("_"):
                continue
            assert not name.startswith(forbidden), f"{cls.__name__}.{name} looks like a write"


def test_writes_are_disabled_on_both_adapters() -> None:
    assert RealHomeAssistantAdapter.writes_enabled is False
    assert MockHomeAssistantAdapter.writes_enabled is False


def test_the_mock_adapter_cannot_reach_the_network() -> None:
    import inspect

    source = inspect.getsource(inspect.getmodule(MockHomeAssistantAdapter))
    for forbidden in ("import httpx", "import requests", "import aiohttp", "urlopen"):
        assert forbidden not in source


# --- adapter selection ------------------------------------------------------
def test_auto_uses_the_real_bridge_when_the_token_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", TEST_TOKEN)
    adapter = build_adapter(Settings(adapter="auto"))
    assert isinstance(adapter, RealHomeAssistantAdapter)


def test_auto_falls_back_to_mock_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    adapter = build_adapter(Settings(adapter="auto"))
    assert isinstance(adapter, MockHomeAssistantAdapter)


def test_real_without_a_token_falls_back_rather_than_failing_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    adapter = build_adapter(Settings(adapter="real"))
    assert isinstance(adapter, MockHomeAssistantAdapter)


def test_explicit_mock_is_honoured_even_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", TEST_TOKEN)
    adapter = build_adapter(Settings(adapter="mock"))
    assert isinstance(adapter, MockHomeAssistantAdapter)


def test_the_token_is_not_a_settings_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """It must not be serialisable via model_dump()."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", TEST_TOKEN)
    settings = Settings()
    assert TEST_TOKEN not in str(settings.model_dump())
    assert settings.ha_token == TEST_TOKEN
