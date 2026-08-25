"""The real Home Assistant adapter.

Talks to Home Assistant Core through the Supervisor proxy using the token the
Supervisor injects. Only Bobi's `script.bobi_cc_*` bridge services are called —
this adapter never enumerates entities, never reads arbitrary states, and never
calls a service that changes anything.

Security invariants enforced here:

* `SUPERVISOR_TOKEN` is read once from settings and lives only in the
  `Authorization` header of outgoing requests.
* Authorization headers are never logged.
* Response bodies are logged only when `BOBI_DEBUG_HTTP` is explicitly enabled,
  so real household data does not land in the add-on log by default.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from app.adapters.base import HomeAssistantAdapter
from app.config import Settings
from app.errors import BobiError, UpstreamError
from app.models.bridge import (
    BridgeCapabilities,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeModel,
    BridgeProbe,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTasks,
    BridgeUsers,
    ConnectionInfo,
)

logger = logging.getLogger("bobi.ha")

T = TypeVar("T", bound=BridgeModel)

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
        endpoint, so the result is unwrapped defensively:

        * `{"service_response": {...}}` → the inner object (current shape);
        * a bare object → itself;
        * a single-element list wrapping either of the above → unwrapped.
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
            logger.debug("→ %s %s data=%s", domain, service, data)

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

    async def _fetch(
        self,
        service: str,
        model: type[T],
        data: dict[str, Any] | None = None,
    ) -> T:
        """Call a bridge script and validate the result into `model`."""
        payload = await self.call_service("script", service, data)

        if payload is None:
            # A script that returns nothing is a valid-but-empty response.
            return model()
        if not isinstance(payload, dict):
            raise UpstreamError(
                "התקבל מבנה נתונים לא צפוי מ-Home Assistant",
                code="bridge_bad_shape",
                details={"service": service, "type": type(payload).__name__},
            )

        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise UpstreamError(
                "לא הצלחתי לקרוא את התשובה מבובי",
                code="bridge_validation_failed",
                details={"service": service, "errors": exc.error_count()},
            ) from exc

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
        status = await self._fetch(STATUS, BridgeStatus)
        # Phase 2 never trusts an upstream "writes are fine".
        status.writes_enabled = False
        return status

    async def get_devices(
        self, scope: str = "all", include_unavailable: bool = True
    ) -> BridgeDevices:
        return await self._fetch(
            DEVICES,
            BridgeDevices,
            {"scope": scope, "include_unavailable": include_unavailable},
        )

    async def get_capabilities(self) -> BridgeCapabilities:
        return await self._fetch(CAPABILITIES, BridgeCapabilities)

    async def get_users(self) -> BridgeUsers:
        return await self._fetch(USERS, BridgeUsers)

    async def get_shabbat(self) -> BridgeShabbat:
        shabbat = await self._fetch(SHABBAT, BridgeShabbat)
        shabbat.writes_enabled = False
        return shabbat

    async def get_rules(self) -> BridgeRules:
        return await self._fetch(RULES, BridgeRules)

    async def get_tasks(self) -> BridgeTasks:
        return await self._fetch(TASKS, BridgeTasks)

    async def get_diagnostics(self) -> BridgeDiagnostics:
        return await self._fetch(DIAGNOSTICS, BridgeDiagnostics)

    async def probe(self, text: str) -> BridgeProbe:
        result = await self._fetch(PROBE, BridgeProbe, {"text": text})
        # Restated locally regardless of what the bridge returned.
        result.probe_only = True
        result.would_execute = False
        return result


def extract_service_response(payload: Any) -> Any:
    """Unwrap a Home Assistant service-call response.

    Kept module-level and pure so the unwrapping rules are unit-testable
    without a client or a server.
    """
    # Some versions wrap the whole thing in a single-element list.
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
