"""Native Home Assistant REST client for Bobi Next.

This transport deliberately exposes only the two operations the deterministic
executor needs: read one entity and call one already-planned HA service.  It
contains no script/helper bridge knowledge and never logs or returns the
Supervisor token.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

_SERVICE_PART = re.compile(r"^[a-z0-9_]+$")


class NativeHAError(RuntimeError):
    """A normalized Home Assistant transport/protocol failure."""


class HomeAssistantNativeClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        token: str,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds
        self._http = http_client
        self._owns_http = http_client is None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        entity = entity_id.strip()
        if not entity or "." not in entity:
            raise ValueError("invalid_entity_id")
        url = f"{self.api_base_url}/states/{quote(entity, safe='._-')}"
        try:
            response = await self._client().get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise NativeHAError("ha_state_timeout") from exc
        except httpx.HTTPError as exc:
            raise NativeHAError("ha_state_transport_error") from exc

        if response.status_code == 404:
            return None
        if response.status_code == 401:
            raise NativeHAError("ha_unauthorized")
        try:
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise NativeHAError(f"ha_state_http_{response.status_code}") from exc
        except ValueError as exc:
            raise NativeHAError("ha_state_invalid_json") from exc
        if not isinstance(payload, dict):
            raise NativeHAError("ha_state_invalid_shape")
        return payload

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
    ) -> Any:
        clean_domain = domain.strip()
        clean_service = service.strip()
        if not _SERVICE_PART.fullmatch(clean_domain):
            raise ValueError("invalid_service_domain")
        if not _SERVICE_PART.fullmatch(clean_service):
            raise ValueError("invalid_service_name")
        if not isinstance(data, dict):
            raise TypeError("service_data_must_be_dict")

        url = f"{self.api_base_url}/services/{clean_domain}/{clean_service}"
        try:
            response = await self._client().post(
                url,
                json=data,
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise NativeHAError("ha_service_timeout") from exc
        except httpx.HTTPError as exc:
            raise NativeHAError("ha_service_transport_error") from exc

        if response.status_code == 401:
            raise NativeHAError("ha_unauthorized")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NativeHAError(f"ha_service_http_{response.status_code}") from exc

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise NativeHAError("ha_service_invalid_json") from exc
