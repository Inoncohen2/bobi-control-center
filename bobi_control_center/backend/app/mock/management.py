"""An in-memory write bridge, for exercising the flow — wired to nothing.

This is a **test double**, not a mode of the application. Neither adapter
returns it from `management_bridge()`, so no running instance of Bobi Control
Center — mock or real — has a write path. It exists so the preview → confirm →
commit → verify flow can be tested end to end without inventing what the real
Home Assistant contract will look like.

That distinction matters: simulating a management bridge inside the mock
adapter would mean guessing the HA-side service names and schemas, and then
shipping a UI built against a guess. The mock adapter therefore fails closed
exactly like the real one, and a developer sees the same *"ניהול עדיין לא הופעל
ב-Home Assistant"* screen the live install shows today.
"""

from __future__ import annotations

import secrets
from typing import Any

from app.adapters.management import ManagementBridge
from app.errors import BobiError
from app.models.manage import (
    ManagedOperation,
    ManagementResource,
    ManagementStatus,
    VerificationResult,
)


class MockManagementBridge(ManagementBridge):
    """Keeps tasks and feature flags in a dict and reads them back honestly."""

    def __init__(
        self,
        *,
        tasks: dict[str, dict[str, Any]] | None = None,
        features: dict[str, bool] | None = None,
        available: bool = True,
        fail_on: str | None = None,
        verifies: bool = True,
    ) -> None:
        self.tasks: dict[str, dict[str, Any]] = tasks or {}
        self.features: dict[str, bool] = features or {}
        self._available = available
        #: An operation this bridge should refuse, so the failure path is testable.
        self._fail_on = fail_on
        #: When False, the write lands but the read-back cannot confirm it.
        self._verifies = verifies
        #: Every apply() call, so a test can assert a preview made none.
        self.applied: list[dict[str, Any]] = []

    async def status(self) -> ManagementStatus:
        if not self._available:
            return ManagementStatus(available=False, reason="ניהול עדיין לא הופעל ב-Home Assistant")
        return ManagementStatus(
            available=True,
            contract_version="mock-1",
            resources=[
                ManagementResource(
                    id="tasks",
                    label="משימות",
                    available=True,
                    operations=[
                        ManagedOperation(id="create", label="הוספת משימה"),
                        ManagedOperation(id="rename", label="שינוי שם"),
                        ManagedOperation(id="complete", label="סימון כבוצעה"),
                        ManagedOperation(id="reopen", label="החזרה לפעילה"),
                        ManagedOperation(id="delete", label="מחיקה", destructive=True),
                    ],
                ),
                ManagementResource(
                    id="features",
                    label="תכונות",
                    available=True,
                    operations=[ManagedOperation(id="set", label="הפעלה או כיבוי")],
                ),
            ],
        )

    async def apply(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> str | None:
        self.applied.append(
            {
                "resource_type": resource_type,
                "operation": operation,
                "resource_id": resource_id,
                "payload": payload,
            }
        )
        if self._fail_on == operation:
            raise BobiError("הגשר סירב לבצע את הפעולה", code="bridge_refused")

        if resource_type == "tasks":
            return self._apply_task(operation, resource_id, payload)
        if resource_type == "features" and resource_id is not None:
            self.features[resource_id] = bool(payload.get("enabled"))
            return resource_id
        raise BobiError("משאב לא נתמך", code="unsupported_resource")

    def _apply_task(
        self, operation: str, resource_id: str | None, payload: dict[str, Any]
    ) -> str | None:
        if operation == "create":
            new_id = f"task_{secrets.token_hex(4)}"
            self.tasks[new_id] = {
                "title": payload.get("title"),
                "owner": payload.get("owner"),
                "completed": False,
            }
            return new_id

        task = self.tasks.get(resource_id or "")
        if task is None:
            raise BobiError("המשימה לא נמצאה", code="not_found")

        if operation == "rename":
            task["title"] = payload.get("title")
        elif operation == "complete":
            task["completed"] = True
        elif operation == "reopen":
            task["completed"] = False
        elif operation == "delete":
            self.tasks.pop(resource_id or "", None)
        return resource_id

    async def verify(
        self,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> VerificationResult:
        if not self._verifies:
            return VerificationResult(
                verified=False,
                method="read_after_write",
                detail="לא הצלחנו לקרוא את הערך בחזרה",
            )

        if resource_type == "features":
            actual = self.features.get(resource_id or "")
            ok = actual == bool(payload.get("enabled"))
        elif operation == "delete":
            ok = (resource_id or "") not in self.tasks
        else:
            task = self.tasks.get(resource_id or "")
            if task is None:
                ok = False
            elif operation == "create" or operation == "rename":
                ok = task.get("title") == payload.get("title")
            elif operation == "complete":
                ok = task.get("completed") is True
            else:
                ok = task.get("completed") is False

        return VerificationResult(
            verified=ok,
            method="read_after_write",
            detail=None if ok else "הערך שנקרא בחזרה אינו תואם למבוקש",
        )
