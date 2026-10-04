from __future__ import annotations

import httpx
import pytest

from app.bobi_next.ha_productivity import CalendarAdapter, TodoAdapter
from app.bobi_next.ha_response import HomeAssistantResponseClient


class FakeProductivityClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.responses: dict[tuple[str, str], dict] = {}

    async def call_service(self, domain: str, service: str, data: dict):
        self.calls.append((domain, service, data))
        return None

    async def call_service_response(self, domain: str, service: str, data: dict):
        self.calls.append((domain, service, data))
        return self.responses.get((domain, service), {})


@pytest.mark.asyncio
async def test_response_client_requests_service_response_only() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "changed_states": [],
                "service_response": {
                    "calendar.family": {"events": [{"summary": "Dinner"}]}
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = HomeAssistantResponseClient(
            api_base_url="http://supervisor/core/api",
            token="test-token",
            http_client=http,
        )
        response = await client.call_service_response(
            "calendar",
            "get_events",
            {"entity_id": ["calendar.family"], "duration": {"hours": 24}},
        )

    assert response["calendar.family"]["events"][0]["summary"] == "Dinner"
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/services/calendar/get_events")
    assert "return_response" in requests[0].url.query.decode()


@pytest.mark.asyncio
async def test_calendar_get_events_normalizes_target_buckets() -> None:
    client = FakeProductivityClient()
    client.responses[("calendar", "get_events")] = {
        "calendar.family": {
            "events": [
                {
                    "summary": "Appointment",
                    "start": "2026-10-05 09:00:00",
                    "end": "2026-10-05 10:00:00",
                }
            ]
        }
    }
    adapter = CalendarAdapter(client)

    result = await adapter.get_events(
        ["calendar.family"],
        duration={"hours": 24},
    )

    assert result["calendar.family"][0]["summary"] == "Appointment"
    assert client.calls == [
        (
            "calendar",
            "get_events",
            {"entity_id": ["calendar.family"], "duration": {"hours": 24}},
        )
    ]


@pytest.mark.asyncio
async def test_calendar_rejects_end_and_duration_together() -> None:
    adapter = CalendarAdapter(FakeProductivityClient())
    with pytest.raises(ValueError, match="calendar_end_and_duration_conflict"):
        await adapter.get_events(
            ["calendar.family"],
            end_date_time="2026-10-05 10:00:00",
            duration={"hours": 1},
        )


@pytest.mark.asyncio
async def test_calendar_create_event_uses_fixed_action() -> None:
    client = FakeProductivityClient()
    adapter = CalendarAdapter(client)

    await adapter.create_event(
        "calendar.family",
        summary="School meeting",
        start_date_time="2026-10-05 18:00:00",
        end_date_time="2026-10-05 19:00:00",
        location="School",
    )

    assert client.calls == [
        (
            "calendar",
            "create_event",
            {
                "entity_id": "calendar.family",
                "summary": "School meeting",
                "start_date_time": "2026-10-05 18:00:00",
                "end_date_time": "2026-10-05 19:00:00",
                "location": "School",
            },
        )
    ]


@pytest.mark.asyncio
async def test_todo_get_items_and_update_are_domain_locked() -> None:
    client = FakeProductivityClient()
    client.responses[("todo", "get_items")] = {
        "todo.shopping": {
            "items": [
                {"uid": "item-1", "summary": "Milk", "status": "needs_action"}
            ]
        }
    }
    adapter = TodoAdapter(client)

    items = await adapter.get_items("todo.shopping")
    await adapter.update_item(
        "todo.shopping",
        item="item-1",
        status="completed",
    )

    assert items[0]["uid"] == "item-1"
    assert client.calls[0] == (
        "todo",
        "get_items",
        {"entity_id": "todo.shopping", "status": "needs_action"},
    )
    assert client.calls[1] == (
        "todo",
        "update_item",
        {"entity_id": "todo.shopping", "item": "item-1", "status": "completed"},
    )


@pytest.mark.asyncio
async def test_todo_rejects_wrong_domain_and_status() -> None:
    adapter = TodoAdapter(FakeProductivityClient())
    with pytest.raises(ValueError, match="invalid_todo_entity_id"):
        await adapter.get_items("calendar.family")
    with pytest.raises(ValueError, match="invalid_todo_status"):
        await adapter.get_items("todo.shopping", status="maybe")


@pytest.mark.asyncio
async def test_todo_add_remove_and_remove_completed_use_fixed_actions() -> None:
    client = FakeProductivityClient()
    adapter = TodoAdapter(client)

    await adapter.add_item("todo.shopping", item="Coffee", due_date="2026-10-05")
    await adapter.remove_item("todo.shopping", item="item-7")
    await adapter.remove_completed_items("todo.shopping")

    assert [call[:2] for call in client.calls] == [
        ("todo", "add_item"),
        ("todo", "remove_item"),
        ("todo", "remove_completed_items"),
    ]
