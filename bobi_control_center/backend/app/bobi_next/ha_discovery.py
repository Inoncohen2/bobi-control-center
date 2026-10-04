"""Read-only Home Assistant discovery for the generic Bobi engine.

This client intentionally bypasses `script.bobi_cc_*`: states come from HA's
REST API and entity/device/area registries come from the authenticated HA
WebSocket API.  No write command is implemented in this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets

from .registry import build_registry
from .models import DeviceRecord


class DiscoveryError(RuntimeError):
    pass


@dataclass(slots=True)
class DiscoverySnapshot:
    states: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    areas: list[dict[str, Any]]

    def semantic_devices(self) -> tuple[DeviceRecord, ...]:
        return build_registry(self.states, self.entities, self.devices, self.areas)


def websocket_url_from_api(api_base_url: str) -> str:
    """Translate e.g. http://supervisor/core/api -> ws://supervisor/core/websocket."""
    parsed = urlparse(api_base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path
    if path.endswith("/api"):
        path = path[:-4]
    path = path.rstrip("/") + "/websocket"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


class HomeAssistantDiscoveryClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        token: str,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.ws_url = websocket_url_from_api(self.api_base_url)
        self._token = token
        self._timeout = timeout_seconds
        self._http = http_client
        self._owns_http = http_client is None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    async def _states(self) -> list[dict[str, Any]]:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await self._http.get(f"{self.api_base_url}/states", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DiscoveryError("home_assistant_states_unavailable") from exc
        if not isinstance(payload, list):
            raise DiscoveryError("home_assistant_states_invalid_shape")
        return [row for row in payload if isinstance(row, dict)]

    async def _registries(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        try:
            async with websockets.connect(
                self.ws_url,
                open_timeout=self._timeout,
                close_timeout=5,
                max_size=16 * 1024 * 1024,
            ) as ws:
                hello = json.loads(await ws.recv())
                if hello.get("type") != "auth_required":
                    raise DiscoveryError("ha_ws_auth_protocol_error")
                await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
                auth = json.loads(await ws.recv())
                if auth.get("type") != "auth_ok":
                    raise DiscoveryError("ha_ws_auth_failed")

                results: list[list[dict[str, Any]]] = []
                for msg_id, command in enumerate(
                    (
                        "config/entity_registry/list",
                        "config/device_registry/list",
                        "config/area_registry/list",
                    ),
                    start=1,
                ):
                    await ws.send(json.dumps({"id": msg_id, "type": command}))
                    reply = json.loads(await ws.recv())
                    if reply.get("id") != msg_id or not reply.get("success", False):
                        raise DiscoveryError(f"ha_registry_command_failed:{command}")
                    value = reply.get("result", [])
                    if not isinstance(value, list):
                        raise DiscoveryError(f"ha_registry_invalid_shape:{command}")
                    results.append([row for row in value if isinstance(row, dict)])
                return results[0], results[1], results[2]
        except DiscoveryError:
            raise
        except Exception as exc:  # network/protocol errors are normalized here
            raise DiscoveryError("home_assistant_registry_unavailable") from exc

    async def snapshot(self) -> DiscoverySnapshot:
        states = await self._states()
        entities, devices, areas = await self._registries()
        return DiscoverySnapshot(states=states, entities=entities, devices=devices, areas=areas)
