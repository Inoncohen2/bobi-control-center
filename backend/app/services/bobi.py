"""The Bobi service layer.

Routers call this and nothing else. It owns the business rules — draft
validation, preview construction, derived fields, audit records — and reaches
Home Assistant only through the adapter interface.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.adapters.base import HomeAssistantAdapter
from app.errors import NotFoundError
from app.models import (
    PERMISSION_LABELS,
    Automation,
    AutomationDraft,
    AutomationList,
    CalendarList,
    Capability,
    ChangePreview,
    Device,
    DeviceCategory,
    DeviceList,
    DiagnosticsReport,
    NotificationList,
    NotificationRule,
    OperationResult,
    Permission,
    PermissionInfo,
    PreviewLine,
    ProbeHistory,
    ProbeHistoryEntry,
    ProbeResult,
    SaveTemplateRequest,
    SettingsResponse,
    Severity,
    ShabbatConfig,
    ShabbatDraft,
    ShabbatTemplate,
    SystemStatus,
    Task,
    TaskList,
    TestReport,
    User,
    UserList,
)
from app.services import automations as automation_rules
from app.services import shabbat as shabbat_rules
from app.services.audit import AuditService
from app.services.devices import to_devices
from app.services.preview import PreviewStore, build_preview
from app.timeutil import now

_PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.CONTROL_DEVICES: "להדליק, לכבות ולשנות מצב של מכשירים בבית.",
    Permission.MANAGE_AUTOMATIONS: "ליצור, לערוך ולמחוק אוטומציות ותזמונים.",
    Permission.MANAGE_SHABBAT: "לשנות את תזמוני שעון השבת.",
    Permission.MANAGE_TASKS: "להוסיף ולסמן משימות.",
    Permission.MANAGE_CALENDAR: "לראות ולנהל אירועים ביומן.",
    Permission.VIEW_CAMERAS: "לצפות בתמונות מהמצלמות.",
    Permission.MANAGE_BOBI: "לשנות הגדרות מערכת של בובי.",
}


class BobiService:
    """Facade over one adapter."""

    def __init__(self, adapter: HomeAssistantAdapter, previews: PreviewStore) -> None:
        self._adapter = adapter
        self._previews = previews
        self.audit = AuditService(adapter)
        self._probe_history: list[ProbeHistoryEntry] = []

    @property
    def adapter_name(self) -> str:
        return self._adapter.name

    @property
    def read_only(self) -> bool:
        return self._adapter.read_only

    # --- status -----------------------------------------------------------
    async def get_status(self) -> SystemStatus:
        return await self._adapter.get_system_status()

    # --- devices ----------------------------------------------------------
    async def list_devices(self) -> DeviceList:
        entities = await self._adapter.get_entities()
        devices = to_devices(entities)
        rooms = sorted({device.room for device in devices})
        categories = sorted(
            {device.category for device in devices}, key=lambda c: c.value
        )
        return DeviceList(devices=devices, rooms=rooms, categories=categories)

    async def get_device(self, device_id: str) -> Device:
        listing = await self.list_devices()
        for device in listing.devices:
            if device.id == device_id:
                return device
        raise NotFoundError("לא מצאתי את המכשיר הזה", details={"device_id": device_id})

    async def devices_by_category(self, category: DeviceCategory) -> list[Device]:
        listing = await self.list_devices()
        return [d for d in listing.devices if d.category is category]

    # --- capabilities -----------------------------------------------------
    async def list_capabilities(self) -> list[Capability]:
        return await self._adapter.get_capabilities()

    async def get_capability(self, capability_id: str) -> Capability:
        for capability in await self._adapter.get_capabilities():
            if capability.id == capability_id:
                return capability
        raise NotFoundError("לא מצאתי את היכולת הזו", details={"capability_id": capability_id})

    async def set_capability_enabled(self, capability_id: str, enabled: bool) -> Capability:
        before = await self.get_capability(capability_id)
        updated = await self._adapter.set_capability_enabled(capability_id, enabled)
        await self.audit.record(
            operation="toggle",
            resource_type="capability",
            resource_id=capability_id,
            resource_label=updated.name,
            before={"enabled": before.enabled},
            after={"enabled": updated.enabled},
        )
        return updated

    # --- automations ------------------------------------------------------
    async def list_automations(self) -> AutomationList:
        items = [automation_rules.enrich(a) for a in await self._adapter.get_automations()]
        return AutomationList(automations=items)

    async def get_automation(self, automation_id: str) -> Automation:
        for automation in await self._adapter.get_automations():
            if automation.id == automation_id:
                return automation_rules.enrich(automation)
        raise NotFoundError(
            "לא מצאתי את האוטומציה הזו", details={"automation_id": automation_id}
        )

    async def preview_automation(self, draft: AutomationDraft) -> ChangePreview:
        automation_rules.validate_draft(draft)
        summary = automation_rules.build_summary(draft)
        lines = [PreviewLine(text=summary, emphasis=True)]

        warnings: list[str] = []
        if draft.start_time and draft.end_time:
            lines.append(
                PreviewLine(
                    text=automation_rules.window_label(draft.start_time, draft.end_time)
                )
            )
            if automation_rules.crosses_midnight(draft.start_time, draft.end_time):
                warnings.append("הטווח ממשיך אל היום הבא.")

        listing = await self.list_devices()
        known = {device.id for device in listing.devices}
        for target in draft.targets:
            if target.id not in known:
                warnings.append(f"בובי לא מכיר את {target.name}.")

        return build_preview(
            self._previews,
            operation="automation.save",
            payload=draft.model_dump(mode="json"),
            summary=summary,
            lines=lines,
            warnings=warnings,
        )

    async def save_automation(self, draft: AutomationDraft, token: str) -> OperationResult:
        self._previews.consume(token, "automation.save", draft.model_dump(mode="json"))
        existing = None
        if draft.id:
            try:
                existing = await self.get_automation(draft.id)
            except NotFoundError:
                existing = None

        automation = automation_rules.draft_to_automation(draft, existing)
        saved = await self._adapter.save_automation(automation)
        entry = await self.audit.record(
            operation="update" if existing else "create",
            resource_type="automation",
            resource_id=saved.id,
            resource_label=saved.name,
            before=existing.model_dump(mode="json") if existing else None,
            after=saved.model_dump(mode="json"),
        )
        return OperationResult(
            success=True,
            message=f"נשמר: {saved.name}",
            dry_run=self.read_only,
            applied=not self.read_only,
            audit_id=entry.id,
        )

    async def preview_delete_automation(self, automation_id: str) -> ChangePreview:
        automation = await self.get_automation(automation_id)
        return build_preview(
            self._previews,
            operation="automation.delete",
            payload={"id": automation_id},
            summary=f"למחוק את „{automation.name}”?",
            lines=[
                PreviewLine(text=automation.summary),
                PreviewLine(text="הפעולה לא ניתנת לביטול.", emphasis=True),
            ],
            warnings=["האוטומציה תפסיק לרוץ לגמרי."],
            destructive=True,
        )

    async def delete_automation(self, automation_id: str, token: str) -> OperationResult:
        self._previews.consume(token, "automation.delete", {"id": automation_id})
        automation = await self.get_automation(automation_id)
        await self._adapter.delete_automation(automation_id)
        entry = await self.audit.record(
            operation="delete",
            resource_type="automation",
            resource_id=automation_id,
            resource_label=automation.name,
            before=automation.model_dump(mode="json"),
        )
        return OperationResult(
            success=True,
            message=f"נמחק: {automation.name}",
            dry_run=self.read_only,
            applied=not self.read_only,
            audit_id=entry.id,
        )

    async def set_automation_enabled(self, automation_id: str, enabled: bool) -> Automation:
        automation = await self.get_automation(automation_id)
        before = automation.enabled
        automation.enabled = enabled
        saved = await self._adapter.save_automation(automation)
        await self.audit.record(
            operation="toggle",
            resource_type="automation",
            resource_id=automation_id,
            resource_label=saved.name,
            before={"enabled": before},
            after={"enabled": enabled},
        )
        return automation_rules.enrich(saved)

    async def duplicate_automation(self, automation_id: str) -> Automation:
        original = await self.get_automation(automation_id)
        clone = original.model_copy(deep=True)
        clone.id = f"{original.id}_copy_{uuid.uuid4().hex[:6]}"
        clone.name = f"{original.name} (עותק)"
        clone.enabled = False
        clone.last_triggered = None
        saved = await self._adapter.save_automation(clone)
        await self.audit.record(
            operation="create",
            resource_type="automation",
            resource_id=saved.id,
            resource_label=saved.name,
            after={"duplicated_from": original.id},
        )
        return automation_rules.enrich(saved)

    # --- shabbat ----------------------------------------------------------
    async def get_shabbat(self) -> ShabbatConfig:
        config = await self._adapter.get_shabbat_config()
        return shabbat_rules.enrich_config(config)

    async def preview_shabbat(self, draft: ShabbatDraft) -> ChangePreview:
        shabbat_rules.validate_draft(draft)
        lines, warnings = shabbat_rules.build_preview_lines(draft)
        return build_preview(
            self._previews,
            operation="shabbat.save",
            payload=draft.model_dump(mode="json"),
            summary=shabbat_rules.summarize(draft),
            lines=lines,
            warnings=warnings,
        )

    async def save_shabbat(self, draft: ShabbatDraft, token: str) -> OperationResult:
        self._previews.consume(token, "shabbat.save", draft.model_dump(mode="json"))
        current = await self._adapter.get_shabbat_config()
        before = current.model_dump(mode="json")
        updated = shabbat_rules.apply_draft(current, draft)
        saved = await self._adapter.save_shabbat_config(updated)
        entry = await self.audit.record(
            operation="update",
            resource_type="shabbat",
            resource_id="shabbat_config",
            resource_label="שעון שבת",
            before=before,
            after=saved.model_dump(mode="json"),
        )
        return OperationResult(
            success=True,
            message="תזמוני השבת נשמרו",
            dry_run=self.read_only,
            applied=not self.read_only,
            audit_id=entry.id,
        )

    async def save_shabbat_template(self, request: SaveTemplateRequest) -> ShabbatTemplate:
        config = await self._adapter.get_shabbat_config()
        template = ShabbatTemplate(
            id=f"tpl_{uuid.uuid4().hex[:8]}",
            name=request.name,
            description=request.description,
            created_at=now(),
            schedules=shabbat_rules.recompute_all(request.schedules),
        )
        config.templates.append(template)
        await self._adapter.save_shabbat_config(config)
        await self.audit.record(
            operation="create",
            resource_type="shabbat_template",
            resource_id=template.id,
            resource_label=template.name,
            after={"name": template.name, "schedules": len(template.schedules)},
        )
        return template

    # --- notifications ----------------------------------------------------
    async def list_notifications(self) -> NotificationList:
        return NotificationList(rules=await self._adapter.get_notification_rules())

    async def set_notification_enabled(self, rule_id: str, enabled: bool) -> NotificationRule:
        updated = await self._adapter.set_notification_enabled(rule_id, enabled)
        await self.audit.record(
            operation="toggle",
            resource_type="notification",
            resource_id=rule_id,
            resource_label=updated.name,
            after={"enabled": enabled},
        )
        return updated

    # --- users ------------------------------------------------------------
    async def list_users(self) -> UserList:
        users = await self._adapter.get_users()
        permissions = [
            PermissionInfo(
                id=permission,
                label=PERMISSION_LABELS[permission],
                description=_PERMISSION_DESCRIPTIONS[permission],
            )
            for permission in Permission
        ]
        return UserList(users=users, permissions=permissions)

    async def get_user(self, user_id: str) -> User:
        for user in await self._adapter.get_users():
            if user.id == user_id:
                return user
        raise NotFoundError("לא מצאתי את המשתמש הזה", details={"user_id": user_id})

    async def preview_permissions(
        self, user_id: str, permissions: list[Permission]
    ) -> ChangePreview:
        user = await self.get_user(user_id)
        current = set(user.permissions)
        requested = set(permissions)

        added = [PERMISSION_LABELS[p] for p in requested - current]
        removed = [PERMISSION_LABELS[p] for p in current - requested]

        lines = [PreviewLine(text=f"שינוי הרשאות עבור {user.name}", emphasis=True)]
        lines += [PreviewLine(text=f"נוסף: {label}") for label in added]
        lines += [PreviewLine(text=f"בוטל: {label}") for label in removed]
        if not added and not removed:
            lines.append(PreviewLine(text="אין שינוי בפועל."))

        warnings = []
        if Permission.MANAGE_BOBI in (current - requested):
            warnings.append(f"{user.name} לא יוכל יותר לשנות הגדרות של בובי.")

        return build_preview(
            self._previews,
            operation="user.permissions",
            payload={"user_id": user_id, "permissions": [p.value for p in permissions]},
            summary=f"{len(added)} הרשאות נוספו, {len(removed)} בוטלו",
            lines=lines,
            warnings=warnings,
            destructive=bool(removed),
        )

    async def save_permissions(
        self, user_id: str, permissions: list[Permission], token: str
    ) -> OperationResult:
        payload = {"user_id": user_id, "permissions": [p.value for p in permissions]}
        self._previews.consume(token, "user.permissions", payload)
        user = await self.get_user(user_id)
        before = [p.value for p in user.permissions]
        user.permissions = permissions
        saved = await self._adapter.save_user(user)
        entry = await self.audit.record(
            operation="update",
            resource_type="user",
            resource_id=user_id,
            resource_label=saved.name,
            before={"permissions": before},
            after={"permissions": [p.value for p in permissions]},
        )
        return OperationResult(
            success=True,
            message=f"ההרשאות של {saved.name} עודכנו",
            dry_run=self.read_only,
            applied=not self.read_only,
            audit_id=entry.id,
        )

    # --- tasks & calendar -------------------------------------------------
    async def list_tasks(self) -> TaskList:
        tasks = await self._adapter.get_tasks()
        return TaskList(
            open_tasks=[t for t in tasks if not t.completed],
            completed_tasks=[t for t in tasks if t.completed],
        )

    async def get_task(self, task_id: str) -> Task:
        for task in await self._adapter.get_tasks():
            if task.id == task_id:
                return task
        raise NotFoundError("לא מצאתי את המשימה הזו", details={"task_id": task_id})

    async def update_task(
        self, task_id: str, *, completed: bool | None = None, title: str | None = None
    ) -> Task:
        task = await self.get_task(task_id)
        before = task.model_dump(mode="json")
        if completed is not None:
            task.completed = completed
            task.due_label = "הושלמה" if completed else task.due_label
        if title is not None:
            task.title = title
        saved = await self._adapter.save_task(task)
        await self.audit.record(
            operation="update",
            resource_type="task",
            resource_id=task_id,
            resource_label=saved.title,
            before=before,
            after=saved.model_dump(mode="json"),
        )
        return saved

    async def delete_task(self, task_id: str) -> OperationResult:
        task = await self.get_task(task_id)
        await self._adapter.delete_task(task_id)
        entry = await self.audit.record(
            operation="delete",
            resource_type="task",
            resource_id=task_id,
            resource_label=task.title,
            before=task.model_dump(mode="json"),
        )
        return OperationResult(
            success=True,
            message=f"נמחק: {task.title}",
            dry_run=self.read_only,
            applied=not self.read_only,
            audit_id=entry.id,
        )

    async def list_calendar(self) -> CalendarList:
        return CalendarList(events=await self._adapter.get_calendar_events())

    # --- probe ------------------------------------------------------------
    async def probe(self, text: str) -> ProbeResult:
        result = await self._adapter.preview_text(text)
        # Belt and braces: the API guarantees this regardless of the adapter.
        result.would_execute = False
        self._remember_probe(result)
        return result

    def _remember_probe(self, result: ProbeResult) -> None:
        entry = ProbeHistoryEntry(
            id=f"probe_{uuid.uuid4().hex[:8]}",
            text=result.original_text,
            family=result.family,
            summary=self._probe_summary(result),
            timestamp=now(),
            safe=result.safe,
        )
        self._probe_history.insert(0, entry)
        del self._probe_history[20:]

    @staticmethod
    def _probe_summary(result: ProbeResult) -> str:
        parts: list[str] = []
        if result.target.name:
            parts.append(result.target.name)
        if result.schedule and result.schedule.description:
            parts.append(result.schedule.description)
        if result.skill:
            parts.append(result.skill)
        return " · ".join(parts) or "לא זוהתה כוונה"

    def probe_history(self) -> ProbeHistory:
        return ProbeHistory(entries=list(self._probe_history))

    # --- diagnostics, tests, audit, settings ------------------------------
    async def get_diagnostics(self) -> DiagnosticsReport:
        issues = await self._adapter.get_diagnostics()
        return DiagnosticsReport(
            issues=issues,
            ok_count=sum(1 for i in issues if i.severity is Severity.OK),
            warning_count=sum(1 for i in issues if i.severity is Severity.WARNING),
            error_count=sum(1 for i in issues if i.severity is Severity.ERROR),
            generated_at=now(),
        )

    async def get_tests(self) -> TestReport:
        return self._build_report(await self._adapter.get_test_suites())

    async def run_tests(self) -> TestReport:
        suites = await self._adapter.run_test_suites()
        await self.audit.record(
            operation="run",
            resource_type="tests",
            resource_id="regression",
            resource_label="בדיקות רגרסיה",
            after={"suites": len(suites)},
        )
        return self._build_report(suites)

    @staticmethod
    def _build_report(suites: list) -> TestReport:
        last_run: datetime | None = None
        for suite in suites:
            if suite.last_run and (last_run is None or suite.last_run > last_run):
                last_run = suite.last_run
        return TestReport(
            suites=suites,
            total=sum(s.total for s in suites),
            passed=sum(s.passed for s in suites),
            failed=sum(s.failed for s in suites),
            last_run=last_run,
        )

    async def get_settings(self) -> SettingsResponse:
        return SettingsResponse(
            sections=await self._adapter.get_settings(),
            read_only=self.read_only,
        )
