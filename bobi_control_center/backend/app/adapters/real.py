"""The real Home Assistant adapter.

Talks to Home Assistant Core through the Supervisor proxy using the token the
Supervisor injects. Only Bobi's `script.bobi_cc_*` bridge services are called —
this adapter never enumerates entities, never reads arbitrary states, and never
calls a service that changes anything.

Raw responses are handed straight to `app.services.normalize`, which is the only
place that knows bridge field names. This adapter's job is transport, not shape.

Security invariants enforced here:

* `SUPERVISOR_TOKEN` is read from settings and lives only in the
  `Authorization` header of outgoing requests.
* Authorization headers are never logged.
* Response bodies are logged only when `BOBI_DEBUG_HTTP` is explicitly enabled.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters.base import HomeAssistantAdapter
from app.config import Settings
from app.errors import BobiError, UpstreamError
from app.models.bridge import (
    BridgeCapabilities,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeProbe,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTasks,
    BridgeUsers,
    ConnectionInfo,
)
from app.services import normalize

logger = logging.getLogger("bobi.ha")

#: Bridge scripts, without the `script.` domain prefix.
STATUS = "bobi_cc_status"
DEVICES = "bobi_cc_devices"
CAPABILITIES = "bobi_cc_capabilities"
USERS = "bobi_cc_users"
SHABBAT = "bobi_cc_shabbat"
RULES = "bobi_cc_rules"
TASKS = "bobi_cc_tasks"
DIAGNOSTICS = "bobi_cc_diagnostics"
PROBE = "bobi_cc_probe"

#: Every service this adapter is permitted to call. Anything outside this set
#: raises before a request is made, so a typo or a future edit cannot turn into
#: an accidental write.
ALLOWED_SERVICES = frozenset(
    {STATUS, DEVICES, CAPABILITIES, USERS, SHABBAT, RULES, TASKS, DIAGNOSTICS, PROBE}
)


class RealHomeAssistantAdapter(HomeAssistantAdapter):
    """Read-only client for the Bobi Control Center bridge."""

    name = "home_assistant"
    writes_enabled = False

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = settings.ha_base_url.rstrip("/")
        # Held only to build the Authorization header.
        self._token = settings.ha_token
        self._timeout = settings.ha_timeout_seconds
        self._debug_http = settings.debug_http
        self._client = client
        self._owns_client = client is None

    # --- transport --------------------------------------------------------
    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        """Build request headers. Never logged, never returned to a client."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        return_response: bool = True,
    ) -> Any:
        """Call one Home Assistant service and return its response payload.

        `return_response` appends the `?return_response` query parameter, which
        is what makes a script hand back data rather than just firing.

        Home Assistant has shipped more than one response shape for this
        endpoint, so the result is unwrapped defensively — see
        :func:`extract_service_response`.
        """
        if domain == "script" and service not in ALLOWED_SERVICES:
            # Structural guard: this adapter exists to call the read-only
            # bridge and nothing else.
            raise BobiError(
                "השירות המבוקש אינו חלק מגשר הקריאה של בובי",
                code="service_not_allowed",
                status_code=500,
                details={"service": service},
            )

        url = f"{self._base_url}/services/{domain}/{service}"
        params = {"return_response": ""} if return_response else None

        if self._debug_http:
            logger.debug("→ %s.%s data=%s", domain, service, data)

        try:
            response = await self._get_client().post(
                url,
                params=params,
                json=data or {},
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                "Home Assistant לא הגיב בזמן",
                details={"service": f"{domain}.{service}"},
            ) from exc
        except httpx.HTTPError as exc:
            # `exc` may embed the request URL but never the headers.
            raise UpstreamError(
                "לא הצלחתי להתחבר ל-Home Assistant",
                details={"service": f"{domain}.{service}"},
            ) from exc

        self._raise_for_status(response, domain, service)

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "התקבלה תשובה לא תקינה מ-Home Assistant",
                details={"service": f"{domain}.{service}"},
            ) from exc

        if self._debug_http:
            logger.debug("← %s.%s %s", domain, service, payload)

        return extract_service_response(payload)

    @staticmethod
    def _raise_for_status(response: httpx.Response, domain: str, service: str) -> None:
        """Turn a Home Assistant error into a structured Bobi error.

        Errors are surfaced, never swallowed: the caller gets a Hebrew message
        and a `details` block, while the raw body stays server-side.
        """
        if response.is_success:
            return

        service_name = f"{domain}.{service}"
        if response.status_code == 401:
            raise UpstreamError(
                "אין הרשאה לגשת ל-Home Assistant",
                code="ha_unauthorized",
                details={"service": service_name},
            )
        if response.status_code == 404:
            raise UpstreamError(
                f"שירות הגשר {service_name} לא נמצא ב-Home Assistant",
                code="bridge_service_missing",
                details={
                    "service": service_name,
                    "hint": "ודאו שסקריפטי bobi_cc_* מותקנים ב-Home Assistant",
                },
            )
        raise UpstreamError(
            "Home Assistant החזיר שגיאה",
            code="ha_error",
            details={"service": service_name, "status": response.status_code},
        )

    async def _payload(self, service: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a bridge script and return its payload as a plain dict.

        A script that returns nothing is a valid-but-empty response, so it
        becomes `{}` rather than an error — the normalizer will produce an empty
        screen, which is the honest result.
        """
        payload = await self.call_service("script", service, data)

        if payload is None:
            return {}
        if isinstance(payload, list):
            # A bare list is a collection; the normalizers look for it by key,
            # so hand it over under a neutral one.
            return {"items": payload}
        if not isinstance(payload, dict):
            raise UpstreamError(
                "התקבל מבנה נתונים לא צפוי מ-Home Assistant",
                code="bridge_bad_shape",
                details={"service": service, "type": type(payload).__name__},
            )
        return payload

    # --- connection -------------------------------------------------------
    async def connection_info(self) -> ConnectionInfo:
        try:
            await self.get_status()
        except BobiError as exc:
            return ConnectionInfo(
                adapter=self.name,
                connected=False,
                writes_enabled=False,
                detail=exc.message,
            )
        return ConnectionInfo(
            adapter=self.name,
            connected=True,
            writes_enabled=False,
            detail="מחובר לגשר של בובי",
        )

    # --- bridge services --------------------------------------------------
    async def get_status(self) -> BridgeStatus:
        return normalize.normalize_status(await self._payload(STATUS))

    async def get_devices(
        self, scope: str = "all", include_unavailable: bool = True
    ) -> BridgeDevices:
        payload = await self._payload(
            DEVICES, {"scope": scope, "include_unavailable": include_unavailable}
        )
        return normalize.normalize_devices(payload, scope, include_unavailable)

    async def get_capabilities(self) -> BridgeCapabilities:
        return normalize.normalize_capabilities(await self._payload(CAPABILITIES))

    async def get_users(self) -> BridgeUsers:
        return normalize.normalize_users(await self._payload(USERS))

    async def get_shabbat(self) -> BridgeShabbat:
        return normalize.normalize_shabbat(await self._payload(SHABBAT))

    async def get_rules(self) -> BridgeRules:
        return normalize.normalize_rules(await self._payload(RULES))

    async def get_tasks(self) -> BridgeTasks:
        return normalize.normalize_tasks(await self._payload(TASKS))

    async def get_diagnostics(self) -> BridgeDiagnostics:
        return normalize.normalize_diagnostics(await self._payload(DIAGNOSTICS))

    async def probe(self, text: str) -> BridgeProbe:
        payload = await self._payload(PROBE, {"text": text})
        return normalize.normalize_probe(payload, text)


def extract_service_response(payload: Any) -> Any:
    """Unwrap a Home Assistant service-call response.

    Kept module-level and pure so the unwrapping rules are unit-testable
    without a client or a server.

    * `{"service_response": {...}}` → the inner object (current shape)
    * a bare object → itself
    * a single-element list wrapping either → unwrapped
    """
    if isinstance(payload, list):
        if len(payload) == 1:
            return extract_service_response(payload[0])
        if not payload:
            return None
        return payload

    if isinstance(payload, dict):
        if "service_response" in payload:
            # Recurse: the inner value has been seen wrapped in a list too.
            return extract_service_response(payload["service_response"])
        if "response" in payload and isinstance(payload["response"], dict):
            return payload["response"]

    return payload
