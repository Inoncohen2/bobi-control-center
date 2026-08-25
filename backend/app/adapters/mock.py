"""In-memory adapter used for the whole of Phase 1.

It behaves like a real backing store — writes are visible to subsequent reads —
but the writes live in this process only. There is no network client here and no
import of ``httpx``: it is structurally impossible for this adapter to reach a
real Home Assistant.
"""

from __future__ import annotations

import asyncio
import copy
import random

from app.adapters.base import HomeAssistantAdapter
from app.errors import NotFoundError
from app.mock.activity import (
    MOCK_ATTENTION,
    MOCK_COMPONENTS,
    MOCK_DIAGNOSTICS,
    MOCK_TASKS,
    build_activity,
    build_audit_entries,
    build_calendar_events,
    build_stats,
    build_test_suites,
)
from app.mock.catalog import (
    MOCK_CAPABILITIES,
    MOCK_NOTIFICATION_RULES,
    MOCK_SETTINGS,
    MOCK_USERS,
)
from app.mock.entities import MOCK_ENTITIES
from app.mock.schedules import MOCK_AUTOMATIONS, MOCK_SHABBAT_CONFIG
from app.models import (
    AuditEntry,
    Automation,
    CalendarEvent,
    Capability,
    DiagnosticIssue,
    NotificationRule,
    ProbeResult,
    RawEntity,
    SettingsSection,
    ShabbatConfig,
    SystemStatus,
    Task,
    TestSuite,
    User,
)
from app.services.devices import to_devices
from app.services.probe import ProbeEngine
from app.timeutil import hours_ago, now

BOBI_VERSION = "1.0.0-phase1"


class MockHomeAssistantAdapter(HomeAssistantAdapter):
    """Deterministic fixtures plus in-memory mutation."""

    name = "mock"
    read_only = True

    def __init__(self) -> None:
        # Deep copies so a mutation in one test cannot leak into another.
        self._entities: list[RawEntity] = copy.deepcopy(MOCK_ENTITIES)
        self._capabilities: list[Capability] = copy.deepcopy(MOCK_CAPABILITIES)
        self._automations: list[Automation] = copy.deepcopy(MOCK_AUTOMATIONS)
        self._shabbat: ShabbatConfig = copy.deepcopy(MOCK_SHABBAT_CONFIG)
        self._notifications: list[NotificationRule] = copy.deepcopy(MOCK_NOTIFICATION_RULES)
        self._users: list[User] = copy.deepcopy(MOCK_USERS)
        self._tasks: list[Task] = copy.deepcopy(MOCK_TASKS)
        self._calendar: list[CalendarEvent] = build_calendar_events()
        self._diagnostics: list[DiagnosticIssue] = copy.deepcopy(MOCK_DIAGNOSTICS)
        self._suites: list[TestSuite] = build_test_suites()
        self._audit: list[AuditEntry] = build_audit_entries()
        self._settings: list[SettingsSection] = copy.deepcopy(MOCK_SETTINGS)
        self._lock = asyncio.Lock()

    # --- system -----------------------------------------------------------
    async def get_system_status(self) -> SystemStatus:
        active_automations = sum(1 for a in self._automations if a.enabled)
        schedule_count = active_automations + len(
            [s for s in self._shabbat.schedules if s.enabled]
        )
        open_tasks = sum(1 for t in self._tasks if not t.completed)
        attention = list(MOCK_ATTENTION)
        return SystemStatus(
            version=BOBI_VERSION,
            adapter=self.name,
            read_only=self.read_only,
            generated_at=now(),
            components=copy.deepcopy(MOCK_COMPONENTS),
            stats=build_stats(
                active_automations=active_automations,
                schedules=schedule_count,
                notifications=sum(1 for r in self._notifications if r.enabled),
                open_tasks=open_tasks,
                attention=len(attention),
            ),
            activity=build_activity(),
            attention=copy.deepcopy(attention),
        )

    async def get_diagnostics(self) -> list[DiagnosticIssue]:
        return copy.deepcopy(self._diagnostics)

    # --- devices ----------------------------------------------------------
    async def get_entities(self) -> list[RawEntity]:
        return copy.deepcopy(self._entities)

    # --- capabilities -----------------------------------------------------
    async def get_capabilities(self) -> list[Capability]:
        return copy.deepcopy(self._capabilities)

    async def set_capability_enabled(self, capability_id: str, enabled: bool) -> Capability:
        async with self._lock:
            for capability in self._capabilities:
                if capability.id == capability_id:
                    capability.enabled = enabled
                    capability.state_label = "פעיל" if enabled else "כבוי"
                    return copy.deepcopy(capability)
        raise NotFoundError("לא מצאתי את היכולת הזו", details={"capability_id": capability_id})

    # --- automations ------------------------------------------------------
    async def get_automations(self) -> list[Automation]:
        return copy.deepcopy(self._automations)

    async def save_automation(self, automation: Automation) -> Automation:
        async with self._lock:
            for index, existing in enumerate(self._automations):
                if existing.id == automation.id:
                    self._automations[index] = automation
                    return copy.deepcopy(automation)
            self._automations.append(automation)
            return copy.deepcopy(automation)

    async def delete_automation(self, automation_id: str) -> None:
        async with self._lock:
            before = len(self._automations)
            self._automations = [a for a in self._automations if a.id != automation_id]
            if len(self._automations) == before:
                raise NotFoundError(
                    "לא מצאתי את האוטומציה הזו", details={"automation_id": automation_id}
                )

    # --- shabbat ----------------------------------------------------------
    async def get_shabbat_config(self) -> ShabbatConfig:
        return copy.deepcopy(self._shabbat)

    async def save_shabbat_config(self, config: ShabbatConfig) -> ShabbatConfig:
        async with self._lock:
            config.updated_at = now()
            self._shabbat = copy.deepcopy(config)
            return copy.deepcopy(self._shabbat)

    # --- notifications ----------------------------------------------------
    async def get_notification_rules(self) -> list[NotificationRule]:
        return copy.deepcopy(self._notifications)

    async def set_notification_enabled(self, rule_id: str, enabled: bool) -> NotificationRule:
        async with self._lock:
            for rule in self._notifications:
                if rule.id == rule_id:
                    rule.enabled = enabled
                    return copy.deepcopy(rule)
        raise NotFoundError("לא מצאתי את ההתראה הזו", details={"rule_id": rule_id})

    # --- people -----------------------------------------------------------
    async def get_users(self) -> list[User]:
        return copy.deepcopy(self._users)

    async def save_user(self, user: User) -> User:
        async with self._lock:
            for index, existing in enumerate(self._users):
                if existing.id == user.id:
                    self._users[index] = user
                    return copy.deepcopy(user)
        raise NotFoundError("לא מצאתי את המשתמש הזה", details={"user_id": user.id})

    # --- tasks & calendar -------------------------------------------------
    async def get_tasks(self) -> list[Task]:
        return copy.deepcopy(self._tasks)

    async def save_task(self, task: Task) -> Task:
        async with self._lock:
            for index, existing in enumerate(self._tasks):
                if existing.id == task.id:
                    self._tasks[index] = task
                    return copy.deepcopy(task)
            self._tasks.append(task)
            return copy.deepcopy(task)

    async def delete_task(self, task_id: str) -> None:
        async with self._lock:
            before = len(self._tasks)
            self._tasks = [t for t in self._tasks if t.id != task_id]
            if len(self._tasks) == before:
                raise NotFoundError("לא מצאתי את המשימה הזו", details={"task_id": task_id})

    async def get_calendar_events(self) -> list[CalendarEvent]:
        return copy.deepcopy(self._calendar)

    # --- probe ------------------------------------------------------------
    async def preview_text(self, text: str) -> ProbeResult:
        """Probe only. Cannot execute — see ``app.services.probe``."""
        engine = ProbeEngine(to_devices(self._entities))
        return engine.probe(text)

    # --- tests & audit ----------------------------------------------------
    async def get_test_suites(self) -> list[TestSuite]:
        return copy.deepcopy(self._suites)

    async def run_test_suites(self) -> list[TestSuite]:
        async with self._lock:
            moment = now()
            for suite in self._suites:
                # Re-roll the duration a little so a re-run visibly differs.
                suite.duration_ms = int(suite.duration_ms * random.uniform(0.92, 1.08))
                suite.last_run = moment
                suite.passed = suite.total
                suite.failed = 0
                for case in suite.cases:
                    case.passed = True
            return copy.deepcopy(self._suites)

    async def get_audit_entries(self) -> list[AuditEntry]:
        return sorted(
            copy.deepcopy(self._audit), key=lambda entry: entry.timestamp, reverse=True
        )

    async def append_audit_entry(self, entry: AuditEntry) -> AuditEntry:
        async with self._lock:
            self._audit.append(entry)
            return copy.deepcopy(entry)

    # --- settings ---------------------------------------------------------
    async def get_settings(self) -> list[SettingsSection]:
        return copy.deepcopy(self._settings)

    # --- test helpers -----------------------------------------------------
    def seed_last_run(self) -> None:
        """Used by fixtures that want a deterministic 'last run' timestamp."""
        for suite in self._suites:
            suite.last_run = hours_ago(6)
