"""Audit trail.

Every write path in the service layer records an entry, even in Phase 1 where
the write itself is a dry run. That way the audit log is already complete and
correct the day a real adapter is switched on.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.adapters.base import HomeAssistantAdapter
from app.models import AuditEntry, Source
from app.timeutil import now

_OPERATION_LABELS = {
    "create": "נוצר",
    "update": "עודכן",
    "delete": "נמחק",
    "toggle": "שינוי מצב",
    "probe": "בדיקה",
    "run": "הרצה",
}


class AuditService:
    def __init__(self, adapter: HomeAssistantAdapter) -> None:
        self._adapter = adapter

    async def record(
        self,
        *,
        operation: str,
        resource_type: str,
        resource_id: str,
        resource_label: str | None = None,
        user: str = "ינון",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        success: bool = True,
        source: Source = Source.WEB,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=f"audit_{uuid.uuid4().hex[:12]}",
            timestamp=now(),
            user=user,
            operation=operation,
            operation_label=_OPERATION_LABELS.get(operation, operation),
            resource_type=resource_type,
            resource_id=resource_id,
            resource_label=resource_label,
            before=before,
            after=after,
            success=success,
            source=source,
        )
        return await self._adapter.append_audit_entry(entry)

    async def list(self, limit: int = 100) -> list[AuditEntry]:
        entries = await self._adapter.get_audit_entries()
        return entries[:limit]
