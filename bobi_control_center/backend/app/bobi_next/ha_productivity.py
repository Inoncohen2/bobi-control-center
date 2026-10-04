"""Safe native Home Assistant adapters for calendar and to-do capabilities.

These adapters expose fixed product operations instead of a generic HA action
surface.  The understanding layer can request calendar/to-do semantics, while
only deterministic code chooses the concrete Home Assistant action and fields.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_TODO_STATUSES = {"needs_action", "completed"}
_DURATION_KEYS = {"days", "hours", "minutes", "seconds"}


class ProductivityHAClient(Protocol):
    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
    ) -> Any: ...

    async def call_service_response(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
    ) -> dict[str, Any]: ...


def _entity_id(value: str, domain: str) -> str:
    entity_id = str(value or "").strip().casefold()
    if not _ENTITY_ID.fullmatch(entity_id) or not entity_id.startswith(f"{domain}."):
        raise ValueError(f"invalid_{domain}_entity_id")
    return entity_id


def _required_text(value: str, field: str, *, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    if len(text) > limit:
        raise ValueError(f"{field}_too_long")
    return text


def _duration(value: Mapping[str, int] | None) -> dict[str, int] | None:
    if value is None:
        return None
    result: dict[str, int] = {}
    for key, raw in value.items():
        if key not in _DURATION_KEYS:
            raise ValueError("invalid_calendar_duration_key")
        amount = int(raw)
        if amount < 0:
            raise ValueError("invalid_calendar_duration")
        result[key] = amount
    if not result or not any(result.values()):
        raise ValueError("calendar_duration_required")
    return result


class CalendarAdapter:
    def __init__(self, client: ProductivityHAClient) -> None:
        self.client = client

    async def get_events(
        self,
        entity_ids: Iterable[str],
        *,
        start_date_time: str = "",
        end_date_time: str = "",
        duration: Mapping[str, int] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        calendars = tuple(dict.fromkeys(_entity_id(item, "calendar") for item in entity_ids))
        if not calendars:
            raise ValueError("calendar_target_required")
        duration_value = _duration(duration)
        if end_date_time and duration_value is not None:
            raise ValueError("calendar_end_and_duration_conflict")

        data: dict[str, Any] = {"entity_id": list(calendars)}
        if start_date_time:
            data["start_date_time"] = start_date_time.strip()
        if end_date_time:
            data["end_date_time"] = end_date_time.strip()
        if duration_value is not None:
            data["duration"] = duration_value

        response = await self.client.call_service_response(
            "calendar",
            "get_events",
            data,
        )
        normalized: dict[str, list[dict[str, Any]]] = {}
        for entity_id in calendars:
            bucket = response.get(entity_id, {})
            if not isinstance(bucket, dict):
                raise ValueError("invalid_calendar_response")
            events = bucket.get("events", [])
            if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
                raise ValueError("invalid_calendar_events")
            normalized[entity_id] = [dict(item) for item in events]
        return normalized

    async def create_event(
        self,
        entity_id: str,
        *,
        summary: str,
        start_date_time: str = "",
        end_date_time: str = "",
        start_date: str = "",
        end_date: str = "",
        in_offset: Mapping[str, int] | None = None,
        description: str = "",
        location: str = "",
    ) -> None:
        target = _entity_id(entity_id, "calendar")
        title = _required_text(summary, "calendar_summary", limit=500)
        timed = bool(start_date_time or end_date_time)
        all_day = bool(start_date or end_date)
        relative = in_offset is not None
        if sum((timed, all_day, relative)) != 1:
            raise ValueError("calendar_timing_mode_required")

        data: dict[str, Any] = {"entity_id": target, "summary": title}
        if timed:
            if not start_date_time or not end_date_time:
                raise ValueError("calendar_timed_range_incomplete")
            data["start_date_time"] = start_date_time.strip()
            data["end_date_time"] = end_date_time.strip()
        elif all_day:
            if not start_date or not end_date:
                raise ValueError("calendar_date_range_incomplete")
            data["start_date"] = start_date.strip()
            data["end_date"] = end_date.strip()
        else:
            offset = _duration(in_offset)
            if offset is None or set(offset).difference({"days"}):
                raise ValueError("invalid_calendar_in_offset")
            data["in"] = offset

        if description:
            data["description"] = description[:4000]
        if location:
            data["location"] = location[:1000]
        await self.client.call_service("calendar", "create_event", data)


class TodoAdapter:
    def __init__(self, client: ProductivityHAClient) -> None:
        self.client = client

    async def get_items(
        self,
        entity_id: str,
        *,
        status: str = "needs_action",
    ) -> list[dict[str, Any]]:
        target = _entity_id(entity_id, "todo")
        clean_status = status.strip().casefold()
        if clean_status not in _TODO_STATUSES:
            raise ValueError("invalid_todo_status")
        response = await self.client.call_service_response(
            "todo",
            "get_items",
            {"entity_id": target, "status": clean_status},
        )
        bucket = response.get(target, {})
        if not isinstance(bucket, dict):
            raise ValueError("invalid_todo_response")
        items = bucket.get("items", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("invalid_todo_items")
        return [dict(item) for item in items]

    async def add_item(
        self,
        entity_id: str,
        *,
        item: str,
        due_date: str = "",
        due_datetime: str = "",
        description: str = "",
    ) -> None:
        target = _entity_id(entity_id, "todo")
        if due_date and due_datetime:
            raise ValueError("todo_due_conflict")
        data: dict[str, Any] = {
            "entity_id": target,
            "item": _required_text(item, "todo_item", limit=1000),
        }
        if due_date:
            data["due_date"] = due_date.strip()
        if due_datetime:
            data["due_datetime"] = due_datetime.strip()
        if description:
            data["description"] = description[:4000]
        await self.client.call_service("todo", "add_item", data)

    async def update_item(
        self,
        entity_id: str,
        *,
        item: str,
        rename: str = "",
        status: str = "",
        due_date: str = "",
        due_datetime: str = "",
        description: str | None = None,
    ) -> None:
        target = _entity_id(entity_id, "todo")
        if due_date and due_datetime:
            raise ValueError("todo_due_conflict")
        data: dict[str, Any] = {
            "entity_id": target,
            "item": _required_text(item, "todo_item", limit=1000),
        }
        if rename:
            data["rename"] = _required_text(rename, "todo_rename", limit=1000)
        if status:
            clean_status = status.strip().casefold()
            if clean_status not in _TODO_STATUSES:
                raise ValueError("invalid_todo_status")
            data["status"] = clean_status
        if due_date:
            data["due_date"] = due_date.strip()
        if due_datetime:
            data["due_datetime"] = due_datetime.strip()
        if description is not None:
            data["description"] = str(description)[:4000]
        if len(data) == 2:
            raise ValueError("todo_update_required")
        await self.client.call_service("todo", "update_item", data)

    async def remove_item(self, entity_id: str, *, item: str) -> None:
        target = _entity_id(entity_id, "todo")
        await self.client.call_service(
            "todo",
            "remove_item",
            {
                "entity_id": target,
                "item": _required_text(item, "todo_item", limit=1000),
            },
        )

    async def remove_completed_items(self, entity_id: str) -> None:
        target = _entity_id(entity_id, "todo")
        await self.client.call_service(
            "todo",
            "remove_completed_items",
            {"entity_id": target},
        )
