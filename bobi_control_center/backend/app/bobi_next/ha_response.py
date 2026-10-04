"""Response-capable Home Assistant actions for Bobi-owned read modules.

Home Assistant actions such as ``calendar.get_events`` and ``todo.get_items``
require the REST ``return_response`` flag.  This subclass keeps that transport
separate from the mutation executor so language models never receive a generic
response-capable action primitive.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .ha_control import HomeAssistantNativeClient, NativeHAError

_SERVICE_PART = re.compile(r"^[a-z0-9_]+$")


class HomeAssistantResponseClient(HomeAssistantNativeClient):
    async def call_service_response(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        clean_domain = domain.strip()
        clean_service = service.strip()
        if not _SERVICE_PART.fullmatch(clean_domain):
            raise ValueError("invalid_service_domain")
        if not _SERVICE_PART.fullmatch(clean_service):
            raise ValueError("invalid_service_name")
        if not isinstance(data, dict):
            raise TypeError("service_data_must_be_dict")

        url = (
            f"{self.api_base_url}/services/{clean_domain}/{clean_service}"
            "?return_response"
        )
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
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise NativeHAError(f"ha_service_http_{response.status_code}") from exc
        except ValueError as exc:
            raise NativeHAError("ha_service_invalid_json") from exc

        if not isinstance(payload, dict):
            raise NativeHAError("ha_service_response_invalid_shape")
        service_response = payload.get("service_response")
        if not isinstance(service_response, dict):
            raise NativeHAError("ha_service_response_invalid_data")
        return service_response
