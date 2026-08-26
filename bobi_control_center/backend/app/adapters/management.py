"""The seam a Home Assistant write bridge plugs into.

Phase 2 kept read-only honest by giving `HomeAssistantAdapter` no write method
at all. Phase 3A keeps it honest a different way: writes exist, but only
through this interface, and only through the operations a bridge declares.

Four properties matter more than anything else here:

* **Absent means refused.** `management_bridge()` returns `None` by default, and
  every route checks. There is no fallback path that calls a service anyway.
* **Discovery is the bridge's job, not configuration's.** There is deliberately
  no setting, flag or environment variable in this file. Management turns on
  when Home Assistant says so and in no other way — including the master write
  switch, which this application can read and can never set.
* **The operations are named, not open.** `apply()` takes an operation from a
  closed set, never a service id. This interface cannot express "call
  `todo.add_item`", let alone "call anything".
* **The two safety layers stay independent.** The bridge does its own
  whitelisting, expected-state checking and read-after-write; this application
  does its own token, expiry, single-use and confirmation checks. Neither is
  relaxed because the other exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.models.manage import (
    BridgeOutcome,
    ManagementStatus,
    ObservedState,
    ResourceSnapshot,
    TaskSnapshot,
)

#: Shown whenever management is asked for and no bridge has declared itself.
UNAVAILABLE_MESSAGE = "ניהול עדיין לא הופעל ב-Home Assistant"

#: Shown when the bridge is present but Home Assistant's master write switch is
#: off. Deliberately the same sentence: from a household member's point of view
#: it is the same situation, and it is not an error.
WRITES_DISABLED_MESSAGE = UNAVAILABLE_MESSAGE


class ManagementBridge(ABC):
    """A declared, verified write path into Bobi."""

    @abstractmethod
    async def status(self) -> ManagementStatus:
        """The contract. Must be discovered from Home Assistant, never assumed."""

    @abstractmethod
    async def snapshot(self) -> TaskSnapshot:
        """The task list a preview binds to. READ ONLY."""

    @abstractmethod
    async def resource_snapshot(self, resource: str) -> ResourceSnapshot:
        """One 3.0 family's current state, normalized. READ ONLY.

        A family whose bridge service has not shipped answers `available:
        false` with a Hebrew reason rather than raising. That is a real answer —
        the screen says the feature is not available in Home Assistant yet —
        and it is the only thing this application may do about a missing
        bridge. There is no fallback that reaches Home Assistant another way.
        """

    @abstractmethod
    async def observe(self, resource_type: str, resource_id: str | None) -> ObservedState | None:
        """Read the current state a preview must bind to. READ ONLY.

        Returning `None` means the state could not be observed. A preview must
        then refuse rather than invent one: the bridge compares this value
        immediately before acting, so a guess would either be rejected as stale
        or — worse — accepted while describing the wrong thing.
        """

    @abstractmethod
    async def apply(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
        preview_token: str,
    ) -> BridgeOutcome:
        """Perform one declared operation and report what happened.

        `preview_token` is the opaque server-side token minted when the preview
        was taken, held only in the preview store and never sent to a client.
        Home Assistant refuses a commit that does not carry one. It is a
        required argument rather than an optional one precisely so a bridge
        cannot be called without it: the shape of the call is what enforces
        "no commit without a preview", not a reviewer's memory.

        The bridge does its own read-after-write, so the outcome's `verified` is
        its answer rather than a guess made here. It must never fall back to a
        generic service call: an operation this bridge does not declare is an
        error, not an invitation to improvise.
        """
