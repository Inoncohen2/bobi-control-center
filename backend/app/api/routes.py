"""The Bobi Management API.

Every response is a typed Pydantic model — no untyped dicts leave this module.
Routes are grouped by resource; each group is a small router mounted under
``/api/bobi``.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query

from app.api.deps import ServiceDep
from app.models import (
    AuditLog,
    Automation,
    AutomationDraft,
    AutomationList,
    CalendarList,
    Capability,
    CapabilityToggleRequest,
    ChangePreview,
    Device,
    DeviceList,
    DiagnosticsReport,
    NotificationList,
    NotificationRule,
    OperationResult,
    PermissionUpdateRequest,
    ProbeHistory,
    ProbeRequest,
    ProbeResult,
    SaveTemplateRequest,
    SettingsResponse,
    ShabbatConfig,
    ShabbatDraft,
    ShabbatTemplate,
    SystemStatus,
    Task,
    TaskList,
    TaskUpdateRequest,
    TestReport,
    User,
    UserList,
)

router = APIRouter(prefix="/api/bobi", tags=["bobi"])


# --- status -----------------------------------------------------------------
@router.get("/status", response_model=SystemStatus, summary="מצב המערכת")
async def get_status(service: ServiceDep) -> SystemStatus:
    return await service.get_status()


# --- capabilities -----------------------------------------------------------
@router.get("/capabilities", response_model=list[Capability], summary="יכולות")
async def list_capabilities(service: ServiceDep) -> list[Capability]:
    return await service.list_capabilities()


@router.get("/capabilities/{capability_id}", response_model=Capability)
async def get_capability(capability_id: str, service: ServiceDep) -> Capability:
    return await service.get_capability(capability_id)


@router.post("/capabilities/{capability_id}/toggle", response_model=Capability)
async def toggle_capability(
    capability_id: str,
    payload: CapabilityToggleRequest,
    service: ServiceDep,
) -> Capability:
    return await service.set_capability_enabled(capability_id, payload.enabled)


# --- devices ----------------------------------------------------------------
@router.get("/devices", response_model=DeviceList, summary="מכשירים")
async def list_devices(service: ServiceDep) -> DeviceList:
    return await service.list_devices()


@router.get("/devices/{device_id}", response_model=Device)
async def get_device(device_id: str, service: ServiceDep) -> Device:
    return await service.get_device(device_id)


# --- automations ------------------------------------------------------------
@router.get("/automations", response_model=AutomationList, summary="אוטומציות")
async def list_automations(service: ServiceDep) -> AutomationList:
    return await service.list_automations()


@router.get("/automations/{automation_id}", response_model=Automation)
async def get_automation(automation_id: str, service: ServiceDep) -> Automation:
    return await service.get_automation(automation_id)


@router.post("/automations/preview", response_model=ChangePreview, summary="תצוגה מקדימה")
async def preview_automation(draft: AutomationDraft, service: ServiceDep) -> ChangePreview:
    return await service.preview_automation(draft)


@router.post("/automations/confirm", response_model=OperationResult, summary="שמירה")
async def confirm_automation(
    service: ServiceDep,
    draft: AutomationDraft = Body(..., embed=True),
    token: str = Body(..., embed=True),
) -> OperationResult:
    return await service.save_automation(draft, token)


@router.post("/automations/{automation_id}/delete/preview", response_model=ChangePreview)
async def preview_delete_automation(automation_id: str, service: ServiceDep) -> ChangePreview:
    return await service.preview_delete_automation(automation_id)


@router.post("/automations/{automation_id}/delete/confirm", response_model=OperationResult)
async def confirm_delete_automation(
    automation_id: str,
    service: ServiceDep,
    token: str = Body(..., embed=True),
) -> OperationResult:
    return await service.delete_automation(automation_id, token)


@router.post("/automations/{automation_id}/toggle", response_model=Automation)
async def toggle_automation(
    automation_id: str,
    service: ServiceDep,
    enabled: bool = Body(..., embed=True),
) -> Automation:
    return await service.set_automation_enabled(automation_id, enabled)


@router.post("/automations/{automation_id}/duplicate", response_model=Automation)
async def duplicate_automation(automation_id: str, service: ServiceDep) -> Automation:
    return await service.duplicate_automation(automation_id)


# --- shabbat ----------------------------------------------------------------
@router.get("/shabbat", response_model=ShabbatConfig, summary="שעון שבת")
async def get_shabbat(service: ServiceDep) -> ShabbatConfig:
    return await service.get_shabbat()


@router.post("/shabbat/preview", response_model=ChangePreview)
async def preview_shabbat(draft: ShabbatDraft, service: ServiceDep) -> ChangePreview:
    return await service.preview_shabbat(draft)


@router.post("/shabbat/confirm", response_model=OperationResult)
async def confirm_shabbat(
    service: ServiceDep,
    draft: ShabbatDraft = Body(..., embed=True),
    token: str = Body(..., embed=True),
) -> OperationResult:
    return await service.save_shabbat(draft, token)


@router.post("/shabbat/templates", response_model=ShabbatTemplate)
async def save_shabbat_template(
    payload: SaveTemplateRequest, service: ServiceDep
) -> ShabbatTemplate:
    return await service.save_shabbat_template(payload)


# --- notifications ----------------------------------------------------------
@router.get("/notifications", response_model=NotificationList, summary="הודעות חכמות")
async def list_notifications(service: ServiceDep) -> NotificationList:
    return await service.list_notifications()


@router.post("/notifications/{rule_id}/toggle", response_model=NotificationRule)
async def toggle_notification(
    rule_id: str,
    service: ServiceDep,
    enabled: bool = Body(..., embed=True),
) -> NotificationRule:
    return await service.set_notification_enabled(rule_id, enabled)


# --- users ------------------------------------------------------------------
@router.get("/users", response_model=UserList, summary="משתמשים")
async def list_users(service: ServiceDep) -> UserList:
    return await service.list_users()


@router.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str, service: ServiceDep) -> User:
    return await service.get_user(user_id)


@router.post("/users/{user_id}/permissions/preview", response_model=ChangePreview)
async def preview_permissions(
    user_id: str, payload: PermissionUpdateRequest, service: ServiceDep
) -> ChangePreview:
    return await service.preview_permissions(user_id, payload.permissions)


@router.post("/users/{user_id}/permissions/confirm", response_model=OperationResult)
async def confirm_permissions(
    user_id: str,
    service: ServiceDep,
    payload: PermissionUpdateRequest = Body(..., embed=True),
    token: str = Body(..., embed=True),
) -> OperationResult:
    return await service.save_permissions(user_id, payload.permissions, token)


# --- tasks & calendar -------------------------------------------------------
@router.get("/tasks", response_model=TaskList, summary="משימות")
async def list_tasks(service: ServiceDep) -> TaskList:
    return await service.list_tasks()


@router.patch("/tasks/{task_id}", response_model=Task)
async def update_task(
    task_id: str, payload: TaskUpdateRequest, service: ServiceDep
) -> Task:
    return await service.update_task(
        task_id, completed=payload.completed, title=payload.title
    )


@router.delete("/tasks/{task_id}", response_model=OperationResult)
async def delete_task(task_id: str, service: ServiceDep) -> OperationResult:
    return await service.delete_task(task_id)


@router.get("/calendar", response_model=CalendarList, summary="יומן")
async def list_calendar(service: ServiceDep) -> CalendarList:
    return await service.list_calendar()


# --- probe ------------------------------------------------------------------
@router.post("/probe", response_model=ProbeResult, summary="בדיקה בלי לבצע")
async def probe(payload: ProbeRequest, service: ServiceDep) -> ProbeResult:
    """Run text through Bobi's pipeline **without executing anything**."""
    return await service.probe(payload.text)


@router.get("/probe/history", response_model=ProbeHistory)
async def probe_history(service: ServiceDep) -> ProbeHistory:
    return service.probe_history()


# --- diagnostics, tests, audit, settings ------------------------------------
@router.get("/diagnostics", response_model=DiagnosticsReport, summary="תקלות")
async def get_diagnostics(service: ServiceDep) -> DiagnosticsReport:
    return await service.get_diagnostics()


@router.get("/tests", response_model=TestReport, summary="בדיקות")
async def get_tests(service: ServiceDep) -> TestReport:
    return await service.get_tests()


@router.post("/tests/run", response_model=TestReport)
async def run_tests(service: ServiceDep) -> TestReport:
    return await service.run_tests()


@router.get("/audit", response_model=AuditLog, summary="יומן פעולות")
async def get_audit(
    service: ServiceDep, limit: int = Query(default=100, ge=1, le=500)
) -> AuditLog:
    entries = await service.audit.list(limit)
    return AuditLog(entries=entries, total=len(entries))


@router.get("/settings", response_model=SettingsResponse, summary="הגדרות")
async def get_settings(service: ServiceDep) -> SettingsResponse:
    return await service.get_settings()
