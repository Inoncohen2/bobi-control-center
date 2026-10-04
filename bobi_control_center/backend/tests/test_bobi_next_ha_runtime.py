from __future__ import annotations

import json

import httpx
import pytest

from app.bobi_next.ha_control import HomeAssistantNativeClient
from app.bobi_next.ha_events import (
    EventStreamAuthError,
    authenticate_and_subscribe,
    normalize_state_changed,
)


class FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = [json.dumps(item) for item in messages]
        self.sent: list[dict] = []

    async def recv(self) -> str:
        return self.messages.pop(0)

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def test_normalize_state_changed_uses_context_id_and_attributes() -> None:
    event = normalize_state_changed(
        {
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "time_fired": "2026-10-04T13:00:00+00:00",
                "context": {"id": "ctx-123"},
                "data": {
                    "entity_id": "sensor.room_temperature",
                    "old_state": {
                        "state": "26.5",
                        "attributes": {"unit_of_measurement": "°C"},
                    },
                    "new_state": {
                        "state": "27.1",
                        "attributes": {"unit_of_measurement": "°C"},
                    },
                },
            },
        }
    )

    assert event is not None
    assert event.event_id == "ctx-123"
    assert event.entity_id == "sensor.room_temperature"
    assert event.old_state == "26.5"
    assert event.new_state == "27.1"
    assert event.new_attributes["unit_of_measurement"] == "°C"
    assert event.occurred_ts > 0


def test_normalize_state_changed_accepts_entity_becoming_available() -> None:
    event = normalize_state_changed(
        {
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "time_fired": "2026-10-04T13:00:00Z",
                "data": {
                    "entity_id": "switch.example",
                    "old_state": None,
                    "new_state": {"state": "off", "attributes": {}},
                },
            },
        }
    )

    assert event is not None
    assert event.old_state is None
    assert event.new_state == "off"
    assert event.event_id.startswith("switch.example:")


def test_normalize_ignores_non_state_event() -> None:
    assert (
        normalize_state_changed(
            {
                "type": "event",
                "event": {"event_type": "call_service", "data": {}},
            }
        )
        is None
    )


@pytest.mark.asyncio
async def test_authenticate_and_subscribe_uses_standard_ha_protocol() -> None:
    ws = FakeWebSocket(
        [
            {"type": "auth_required", "ha_version": "2026.9.4"},
            {"type": "auth_ok", "ha_version": "2026.9.4"},
            {"id": 1, "type": "result", "success": True, "result": None},
        ]
    )

    await authenticate_and_subscribe(ws, token="test-token")

    assert ws.sent == [
        {"type": "auth", "access_token": "test-token"},
        {"id": 1, "type": "subscribe_events", "event_type": "state_changed"},
    ]


@pytest.mark.asyncio
async def test_authenticate_and_subscribe_fails_closed_on_bad_token() -> None:
    ws = FakeWebSocket(
        [
            {"type": "auth_required"},
            {"type": "auth_invalid", "message": "Invalid access token"},
        ]
    )

    with pytest.raises(EventStreamAuthError, match="ha_ws_auth_failed"):
        await authenticate_and_subscribe(ws, token="wrong-token")


@pytest.mark.asyncio
async def test_native_client_reads_state_and_calls_planned_service() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/states/light.kitchen"):
            return httpx.Response(
                200,
                json={
                    "entity_id": "light.kitchen",
                    "state": "off",
                    "attributes": {},
                },
            )
        if request.url.path.endswith("/services/light/turn_on"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = HomeAssistantNativeClient(
            api_base_url="http://supervisor/core/api",
            token="supervisor-secret",
            http_client=http,
        )
        state = await client.get_state("light.kitchen")
        response = await client.call_service(
            "light",
            "turn_on",
            {"entity_id": "light.kitchen", "brightness_pct": 40},
        )

    assert state is not None and state["state"] == "off"
    assert response == []
    assert len(requests) == 2
    assert requests[0].headers["authorization"] == "Bearer supervisor-secret"
    assert requests[1].url.path.endswith("/services/light/turn_on")
    assert json.loads(requests[1].content)["brightness_pct"] == 40


@pytest.mark.asyncio
async def test_native_client_returns_none_for_missing_entity() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as http:
        client = HomeAssistantNativeClient(
            api_base_url="http://supervisor/core/api",
            token="token",
            http_client=http,
        )
        assert await client.get_state("switch.missing") is None


@pytest.mark.asyncio
async def test_native_client_rejects_service_path_injection() -> None:
    client = HomeAssistantNativeClient(
        api_base_url="http://supervisor/core/api",
        token="token",
    )
    try:
        with pytest.raises(ValueError, match="invalid_service_name"):
            await client.call_service("light", "../states", {})
    finally:
        await client.aclose()
