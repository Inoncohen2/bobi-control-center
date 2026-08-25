"""The seam a Home Assistant write bridge plugs into.

Phase 2 kept read-only honest by giving `HomeAssistantAdapter` no write method
at all. Phase 3A keeps it honest a different way: writes exist, but only
through this interface, and **an adapter has one only if Home Assistant
declares it**.

Three properties matter more than anything else here:

* **Absent means refused.** `management_bridge()` returns `None` by default and
  the real adapter returns `None` today, because no HA-side contract has been
  supplied. Every route checks, and answers *"ניהול עדיין לא הופעל
  ב-Home Assistant"*. There is no fallback path that calls a service anyway.
* **Discovery is the bridge's job, not configuration's.** There is deliberately
  no setting, flag or environment variable in this file. Management turns on
  when Home Assistant says so and in no other way.
* **The operations are named, not open.** A bridge declares which operations it
  supports; anything not declared cannot be requested. `apply()` takes an
  operation name from a closed set, never a service id — this interface cannot
  express "call `todo.add_item`", let alone "call anything".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.models.manage import ManagementStatus, VerificationResult

#: Shown whenever management is asked for and no bridge has declared itself.
UNAVAILABLE_MESSAGE = "ניהול עדיין לא הופעל ב-Home Assistant"


class ManagementBridge(ABC):
    """A declared, verified write path into Bobi.

    An implementation promises three things: it can describe what it supports,
    it can apply one named operation, and it can read the result back.
    """

    @abstractmethod
    async def status(self) -> ManagementStatus:
        """What this bridge supports. Must be discovered, never assumed."""

    @abstractmethod
    async def apply(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> str | None:
        """Perform one declared operation and return the resource's id.

        Raises a `BobiError` on refusal or failure. It must never fall back to
        a generic service call: an operation this bridge does not declare is an
        error, not an invitation to improvise.
        """

    @abstractmethod
    async def verify(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> VerificationResult:
        """Read the resource back and report whether it matches the request.

        Returning `verified=False` is a legitimate answer — the write may have
        landed while the read could not confirm it. Never guess `True`.
        """
