"""Phase 2 placeholder for the real Home Assistant adapter.

**This is intentionally not implemented.** Every method raises, so selecting
``BOBI_ADAPTER=real`` cannot silently produce partial or wrong behaviour, and no
code path here can write to a real installation.

See ``docs/home-assistant-integration.md`` for the implementation plan. The
class exists now so the seam is visible and so the conformance test suite has a
second implementation to point at when the time comes.
"""

from __future__ import annotations

from typing import NoReturn

from app.adapters.base import HomeAssistantAdapter
from app.errors import BobiError


class RealHomeAssistantAdapter(HomeAssistantAdapter):
    """Not implemented in Phase 1."""

    name = "real"
    read_only = True

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        # Stored for Phase 2; never logged and never serialised to a response.
        self._base_url = base_url
        self._token = token

    def _unavailable(self) -> NoReturn:
        raise BobiError(
            "החיבור ל-Home Assistant עדיין לא זמין בגרסה הזו",
            code="adapter_not_implemented",
            status_code=501,
            details={"phase": 1, "adapter": "real"},
        )

    async def get_system_status(self):
        self._unavailable()

    async def get_diagnostics(self):
        self._unavailable()

    async def get_entities(self):
        self._unavailable()

    async def get_capabilities(self):
        self._unavailable()

    async def set_capability_enabled(self, capability_id: str, enabled: bool):
        self._unavailable()

    async def get_automations(self):
        self._unavailable()

    async def save_automation(self, automation):
        self._unavailable()

    async def delete_automation(self, automation_id: str):
        self._unavailable()

    async def get_shabbat_config(self):
        self._unavailable()

    async def save_shabbat_config(self, config):
        self._unavailable()

    async def get_notification_rules(self):
        self._unavailable()

    async def set_notification_enabled(self, rule_id: str, enabled: bool):
        self._unavailable()

    async def get_users(self):
        self._unavailable()

    async def save_user(self, user):
        self._unavailable()

    async def get_tasks(self):
        self._unavailable()

    async def save_task(self, task):
        self._unavailable()

    async def delete_task(self, task_id: str):
        self._unavailable()

    async def get_calendar_events(self):
        self._unavailable()

    async def preview_text(self, text: str):
        self._unavailable()

    async def get_test_suites(self):
        self._unavailable()

    async def run_test_suites(self):
        self._unavailable()

    async def get_audit_entries(self):
        self._unavailable()

    async def append_audit_entry(self, entry):
        self._unavailable()

    async def get_settings(self):
        self._unavailable()
