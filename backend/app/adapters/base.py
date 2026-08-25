"""The single seam between Bobi's domain logic and Home Assistant.

Everything above this interface speaks Bobi vocabulary. Everything below it may
speak Home Assistant vocabulary. Swapping :class:`MockHomeAssistantAdapter` for
``RealHomeAssistantAdapter`` therefore requires no change above this line — and
no change at all in the frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import (
    AuditEntry,
    Automation,
    CalendarEvent,
    Capability,
    DiagnosticIssue,
    NotificationRule,
    RawEntity,
    SettingsSection,
    ShabbatConfig,
    SystemStatus,
    Task,
    TestSuite,
    User,
)


class HomeAssistantAdapter(ABC):
    """Read/write contract for a Bobi backing store.

    Implementations must be safe to call concurrently and must never raise raw
    third-party exceptions — wrap failures in :class:`app.errors.BobiError`.
    """

    #: Identifies the implementation in ``/api/bobi/status``.
    name: str = "abstract"

    #: When True the service layer refuses every write path.
    read_only: bool = True

    # --- system -----------------------------------------------------------
    @abstractmethod
    async def get_system_status(self) -> SystemStatus:
        """Health cards, dashboard stats, activity timeline and warnings."""

    @abstractmethod
    async def get_diagnostics(self) -> list[DiagnosticIssue]:
        """Current issues, phrased for a household member."""

    # --- devices ----------------------------------------------------------
    @abstractmethod
    async def get_entities(self) -> list[RawEntity]:
        """Raw entities. The service layer maps these into Bobi devices."""

    # --- capabilities -----------------------------------------------------
    @abstractmethod
    async def get_capabilities(self) -> list[Capability]:
        """The things Bobi knows how to do."""

    @abstractmethod
    async def set_capability_enabled(self, capability_id: str, enabled: bool) -> Capability:
        """Toggle a capability. In Phase 1 this mutates in-memory state only."""

    # --- automations ------------------------------------------------------
    @abstractmethod
    async def get_automations(self) -> list[Automation]:
        """Bobi automations — never native Home Assistant YAML."""

    @abstractmethod
    async def save_automation(self, automation: Automation) -> Automation:
        """Create or update. Callers must have gone through preview/confirm."""

    @abstractmethod
    async def delete_automation(self, automation_id: str) -> None:
        """Delete. Callers must have gone through preview/confirm."""

    # --- shabbat ----------------------------------------------------------
    @abstractmethod
    async def get_shabbat_config(self) -> ShabbatConfig:
        """The saved (non-draft) Shabbat configuration."""

    @abstractmethod
    async def save_shabbat_config(self, config: ShabbatConfig) -> ShabbatConfig:
        """Persist a confirmed Shabbat configuration."""

    # --- notifications ----------------------------------------------------
    @abstractmethod
    async def get_notification_rules(self) -> list[NotificationRule]:
        """Smart notification rules."""

    @abstractmethod
    async def set_notification_enabled(self, rule_id: str, enabled: bool) -> NotificationRule:
        """Enable/disable one rule."""

    # --- people -----------------------------------------------------------
    @abstractmethod
    async def get_users(self) -> list[User]:
        """Household profiles. Never contains a real phone number."""

    @abstractmethod
    async def save_user(self, user: User) -> User:
        """Persist a user profile (including its permission set)."""

    # --- tasks & calendar -------------------------------------------------
    @abstractmethod
    async def get_tasks(self) -> list[Task]:
        """Open and completed tasks."""

    @abstractmethod
    async def save_task(self, task: Task) -> Task:
        """Create or update a task."""

    @abstractmethod
    async def delete_task(self, task_id: str) -> None:
        """Delete a task."""

    @abstractmethod
    async def get_calendar_events(self) -> list[CalendarEvent]:
        """Upcoming calendar events relevant to Bobi."""

    # --- probe ------------------------------------------------------------
    @abstractmethod
    async def preview_text(self, text: str) -> object:
        """Run text through Bobi's understanding pipeline **without executing**.

        Returns a :class:`app.models.ProbeResult`. The return type is loosened to
        ``object`` here only to avoid a circular import at module scope.
        """

    # --- tests & audit ----------------------------------------------------
    @abstractmethod
    async def get_test_suites(self) -> list[TestSuite]:
        """Automated regression suites."""

    @abstractmethod
    async def run_test_suites(self) -> list[TestSuite]:
        """Re-run the suites. Phase 1 re-rolls mock results."""

    @abstractmethod
    async def get_audit_entries(self) -> list[AuditEntry]:
        """The audit trail, newest first."""

    @abstractmethod
    async def append_audit_entry(self, entry: AuditEntry) -> AuditEntry:
        """Record one write operation."""

    # --- settings ---------------------------------------------------------
    @abstractmethod
    async def get_settings(self) -> list[SettingsSection]:
        """Settings sections. Secret fields must already be masked."""
