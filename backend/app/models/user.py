"""Household user profiles and the permissions matrix."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from .common import BobiModel
from .notification import QuietHours


class Permission(str, Enum):
    CONTROL_DEVICES = "control_devices"
    MANAGE_AUTOMATIONS = "manage_automations"
    MANAGE_SHABBAT = "manage_shabbat"
    MANAGE_TASKS = "manage_tasks"
    MANAGE_CALENDAR = "manage_calendar"
    VIEW_CAMERAS = "view_cameras"
    MANAGE_BOBI = "manage_bobi"


PERMISSION_LABELS: dict[Permission, str] = {
    Permission.CONTROL_DEVICES: "שליטה במכשירים",
    Permission.MANAGE_AUTOMATIONS: "ניהול אוטומציות",
    Permission.MANAGE_SHABBAT: "ניהול שעון שבת",
    Permission.MANAGE_TASKS: "ניהול משימות",
    Permission.MANAGE_CALENDAR: "ניהול יומן",
    Permission.VIEW_CAMERAS: "צפייה במצלמות",
    Permission.MANAGE_BOBI: "ניהול בובי",
}


class NotificationPreferences(BobiModel):
    whatsapp: bool = True
    push: bool = False
    summary_daily: bool = False
    urgent_only: bool = False


class User(BobiModel):
    id: str
    name: str
    enabled: bool = True
    role: str = Field(default="member", description="'admin' | 'member' | 'guest'")
    role_label: str = "בן/בת בית"
    avatar_color: str = "#6366f1"
    whatsapp_connected: bool = False
    whatsapp_hint: str = Field(
        default="",
        description="Masked contact hint. Never a real phone number.",
    )
    calendar: str | None = None
    task_list: str | None = None
    permissions: list[Permission] = Field(default_factory=list)
    notification_preferences: NotificationPreferences = Field(
        default_factory=NotificationPreferences
    )
    quiet_hours: QuietHours = Field(default_factory=QuietHours)


class PermissionInfo(BobiModel):
    id: Permission
    label: str
    description: str


class UserList(BobiModel):
    users: list[User]
    permissions: list[PermissionInfo]


class PermissionUpdateRequest(BobiModel):
    permissions: list[Permission]
