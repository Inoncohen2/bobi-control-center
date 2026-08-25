"""An in-memory stand-in for the Home Assistant write bridge — wired to nothing.

This is a **test double**, not a mode of the application. Neither adapter
returns it from `management_bridge()`, so no running instance uses it. It exists
so the preview → confirm → commit → verify flow can be tested end to end, and it
mimics the real contract closely enough to be worth trusting: the same operation
names, the same `expected_*` comparison, the same `stale_preview` and
`already_in_state` reasons, and the same master switch that defaults to **off**.

That last part matters. `writes_enabled` starts `False` here exactly as it does
in the live install, so the default test is the safe one and enabling it has to
be deliberate.
"""

from __future__ import annotations

import secrets
from typing import Any

from app.adapters.management import UNAVAILABLE_MESSAGE, ManagementBridge
from app.errors import BobiError
from app.models.manage import (
    BridgeOutcome,
    ManagedOperation,
    ManagedTarget,
    ManagementResource,
    ManagementStatus,
    ObservedState,
    SnapshotTask,
    TaskSnapshot,
)

_OPEN = "needs_action"
_COMPLETED = "completed"


class MockManagementBridge(ManagementBridge):
    """Keeps tasks and features in memory and checks them the way HA does."""

    def __init__(
        self,
        *,
        tasks: dict[str, dict[str, Any]] | None = None,
        features: dict[str, bool] | None = None,
        users: dict[str, str] | None = None,
        available: bool = True,
        #: Home Assistant's master switch. Off by default, as it is today.
        writes_enabled: bool = False,
        #: When False, the feature contract omits current state — which must
        #: block a preview rather than be guessed at.
        reports_feature_state: bool = True,
        fail_on: str | None = None,
        verifies: bool = True,
    ) -> None:
        self.tasks: dict[str, dict[str, Any]] = tasks or {}
        self.features: dict[str, bool] = features or {}
        self.users: dict[str, str] = users or {"user_1": "ינון", "user_2": "הודיה"}
        self._available = available
        self.writes_enabled = writes_enabled
        self._reports_feature_state = reports_feature_state
        self._fail_on = fail_on
        self._verifies = verifies
        #: Every apply() call, so a test can assert a preview made none.
        self.applied: list[dict[str, Any]] = []

    async def status(self) -> ManagementStatus:
        if not self._available:
            return ManagementStatus(available=False, reason=UNAVAILABLE_MESSAGE)
        return ManagementStatus(
            available=True,
            contract_version="mock-3a",
            writes_enabled=self.writes_enabled,
            resources=[
                ManagementResource(
                    id="tasks",
                    label="משימות",
                    available=True,
                    operations=[
                        ManagedOperation(id="add", label="הוספת משימה"),
                        ManagedOperation(id="edit", label="שינוי תוכן"),
                        ManagedOperation(id="complete", label="סימון כבוצעה"),
                        ManagedOperation(id="reopen", label="החזרה לפעילה"),
                        ManagedOperation(id="delete", label="מחיקה", destructive=True),
                    ],
                    targets=[
                        ManagedTarget(id=user_id, label=name)
                        for user_id, name in self.users.items()
                    ],
                ),
                ManagementResource(
                    id="features",
                    label="תכונות",
                    available=True,
                    operations=[ManagedOperation(id="set", label="הפעלה או כיבוי")],
                    targets=[
                        ManagedTarget(
                            id=feature_id,
                            label=feature_id,
                            risk="low",
                            enabled=state if self._reports_feature_state else None,
                        )
                        for feature_id, state in self.features.items()
                    ],
                ),
            ],
        )

    async def snapshot(self) -> TaskSnapshot:
        tasks = [
            SnapshotTask(
                uid=uid,
                summary=task["summary"],
                status=task["status"],
                completed=task["status"] == _COMPLETED,
                due=task.get("due") or None,
                owner_id=task["user_id"],
                owner=self.users.get(task["user_id"], task["user_id"]),
            )
            for uid, task in self.tasks.items()
        ]
        return TaskSnapshot(
            count=len(tasks),
            tasks=tasks,
            owners=[ManagedTarget(id=k, label=v) for k, v in self.users.items()],
            writes_enabled=self.writes_enabled,
        )

    async def observe(self, resource_type: str, resource_id: str | None) -> ObservedState | None:
        if resource_type == "tasks":
            if resource_id is None:
                return ObservedState(values={})
            task = self.tasks.get(resource_id)
            if task is None:
                return None
            return ObservedState(
                resource_id=resource_id,
                label=task["summary"],
                values={
                    "summary": task["summary"],
                    "status": task["status"],
                    "user_id": task["user_id"],
                    "owner": self.users.get(task["user_id"], task["user_id"]),
                },
            )

        if resource_type == "features":
            if not self._reports_feature_state or resource_id not in self.features:
                return None
            enabled = self.features[resource_id]
            return ObservedState(
                resource_id=resource_id,
                label=resource_id,
                values={"state": "on" if enabled else "off", "enabled": enabled},
            )
        return None

    async def apply(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
        request_id: str,
    ) -> BridgeOutcome:
        self.applied.append(
            {
                "resource_type": resource_type,
                "operation": operation,
                "resource_id": resource_id,
                "payload": payload,
                "observed": observed.values,
                "request_id": request_id,
            }
        )
        # The bridge's own master switch, checked again on its side.
        if not self.writes_enabled:
            return BridgeOutcome(executed=False, verified=False, reason="writes_disabled")
        if self._fail_on == operation:
            raise BobiError("הגשר סירב לבצע את הפעולה", code="bridge_refused")

        if resource_type == "tasks":
            return self._apply_task(operation, resource_id, payload, observed)
        if resource_type == "features":
            return self._apply_feature(resource_id, payload, observed)
        raise BobiError("משאב לא נתמך", code="unsupported_resource")

    def _apply_task(
        self,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        observed: ObservedState,
    ) -> BridgeOutcome:
        if operation == "add":
            summary = payload.get("summary")
            if any(
                task["summary"] == summary and task["status"] == _OPEN
                for task in self.tasks.values()
            ):
                return BridgeOutcome(executed=False, verified=False, reason="duplicate")
            uid = f"uid_{secrets.token_hex(4)}"
            self.tasks[uid] = {
                "summary": summary,
                "status": _OPEN,
                "user_id": payload.get("user_id"),
                "due": payload.get("due_date") or "",
            }
            return BridgeOutcome(
                executed=True, verified=self._verifies, reason="ok", resource_id=uid
            )

        task = self.tasks.get(resource_id or "")
        if task is None:
            return BridgeOutcome(executed=False, verified=False, reason="not_found")

        # Optimistic locking, exactly as Home Assistant does it: compare what
        # the preview saw against what is true now, and refuse if they differ.
        if (
            task["summary"] != observed.values.get("summary")
            or task["status"] != observed.values.get("status")
        ):
            return BridgeOutcome(executed=False, verified=False, reason="stale_preview")

        if operation == "edit":
            task["summary"] = payload.get("new_summary")
        elif operation == "complete":
            task["status"] = _COMPLETED
        elif operation == "reopen":
            task["status"] = _OPEN
        elif operation == "delete":
            self.tasks.pop(resource_id or "", None)
        return BridgeOutcome(
            executed=True, verified=self._verifies, reason="ok", resource_id=resource_id
        )

    def _apply_feature(
        self, resource_id: str | None, payload: dict[str, Any], observed: ObservedState
    ) -> BridgeOutcome:
        if resource_id not in self.features:
            return BridgeOutcome(executed=False, verified=False, reason="unknown_feature")

        actual = "on" if self.features[resource_id] else "off"
        if actual != observed.values.get("state"):
            return BridgeOutcome(executed=False, verified=False, reason="stale_preview")

        wanted = bool(payload.get("enabled"))
        if self.features[resource_id] == wanted:
            return BridgeOutcome(
                executed=False, verified=True, reason="already_in_state", resource_id=resource_id
            )

        self.features[resource_id] = wanted
        return BridgeOutcome(
            executed=True, verified=self._verifies, reason="ok", resource_id=resource_id
        )
