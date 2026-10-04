"""Home Assistant state_changed WebSocket stream for Bobi Next.

The stream authenticates through the Supervisor WebSocket proxy, subscribes to
`state_changed`, normalizes events into the conditional-engine contract and
reconnects with bounded backoff.  It never performs a Home Assistant mutation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from typing import Any, Protocol

import websockets

from .conditional import StateChangeEvent
from .ha_discovery import websocket_url_from_api

logger = logging.getLogger("bobi.next.ha-events")


class EventStreamError(RuntimeError):
    """Base class for normalized event-stream failures."""


class EventStreamAuthError(EventStreamError):
    """Authentication failed and reconnecting with the same token is pointless."""


class WebSocketLike(Protocol):
    async def recv(self) -> Any: ...

    async def send(self, message: str) -> Any: ...


EventHandler = Callable[[StateChangeEvent], Awaitable[None]]


def _timestamp(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _state_parts(value: Any) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(value, dict):
        return None, {}
    state = value.get("state")
    attrs = value.get("attributes")
    return (
        str(state) if state is not None else None,
        dict(attrs) if isinstance(attrs, dict) else {},
    )


def normalize_state_changed(message: dict[str, Any]) -> StateChangeEvent | None:
    if message.get("type") != "event":
        return None
    event = message.get("event")
    if not isinstance(event, dict) or event.get("event_type") != "state_changed":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None

    entity_id = str(data.get("entity_id") or "").strip()
    if not entity_id:
        return None
    old_state, old_attributes = _state_parts(data.get("old_state"))
    new_state, new_attributes = _state_parts(data.get("new_state"))
    if old_state is None and new_state is None:
        return None

    context = event.get("context")
    context_id = ""
    if isinstance(context, dict):
        context_id = str(context.get("id") or "").strip()
    fired = str(event.get("time_fired") or "").strip()
    event_id = context_id or f"{entity_id}:{fired}:{old_state}->{new_state}"

    return StateChangeEvent(
        event_id=event_id,
        entity_id=entity_id,
        old_state=old_state,
        new_state=new_state,
        old_attributes=old_attributes,
        new_attributes=new_attributes,
        occurred_ts=_timestamp(fired),
    )


async def authenticate_and_subscribe(
    ws: WebSocketLike,
    *,
    token: str,
    subscription_id: int = 1,
) -> None:
    try:
        hello = json.loads(await ws.recv())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EventStreamError("ha_ws_invalid_auth_hello") from exc
    if not isinstance(hello, dict) or hello.get("type") != "auth_required":
        raise EventStreamError("ha_ws_auth_protocol_error")

    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    try:
        auth = json.loads(await ws.recv())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EventStreamError("ha_ws_invalid_auth_reply") from exc
    if not isinstance(auth, dict) or auth.get("type") != "auth_ok":
        raise EventStreamAuthError("ha_ws_auth_failed")

    await ws.send(
        json.dumps(
            {
                "id": subscription_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }
        )
    )
    try:
        reply = json.loads(await ws.recv())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EventStreamError("ha_ws_invalid_subscribe_reply") from exc
    if (
        not isinstance(reply, dict)
        or reply.get("id") != subscription_id
        or not reply.get("success", False)
    ):
        raise EventStreamError("ha_ws_subscribe_failed")


class HomeAssistantEventStream:
    def __init__(
        self,
        *,
        api_base_url: str,
        token: str,
        timeout_seconds: float = 30.0,
        reconnect_min_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        self.ws_url = websocket_url_from_api(api_base_url)
        self._token = token
        self._timeout = max(1.0, float(timeout_seconds))
        self._reconnect_min = max(0.1, float(reconnect_min_seconds))
        self._reconnect_max = max(self._reconnect_min, float(reconnect_max_seconds))

    async def _listen_once(
        self,
        handler: EventHandler,
        *,
        stop_event: asyncio.Event,
    ) -> None:
        async with websockets.connect(
            self.ws_url,
            open_timeout=self._timeout,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=16 * 1024 * 1024,
        ) as ws:
            await authenticate_and_subscribe(ws, token=self._token)
            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                except TimeoutError:
                    continue
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    logger.warning("Ignoring malformed HA WebSocket message")
                    continue
                if not isinstance(message, dict):
                    continue
                event = normalize_state_changed(message)
                if event is not None:
                    await handler(event)

    async def run_forever(
        self,
        handler: EventHandler,
        *,
        stop_event: asyncio.Event,
    ) -> None:
        delay = self._reconnect_min
        while not stop_event.is_set():
            try:
                await self._listen_once(handler, stop_event=stop_event)
                delay = self._reconnect_min
            except asyncio.CancelledError:
                raise
            except EventStreamAuthError:
                raise
            except Exception as exc:
                if stop_event.is_set():
                    return
                logger.warning(
                    "HA event stream disconnected (%s); reconnecting",
                    type(exc).__name__,
                )
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                delay = min(self._reconnect_max, delay * 2)
