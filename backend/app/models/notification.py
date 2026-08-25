"""Smart notification rules."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import Advanced, BobiModel


class QuietHours(BobiModel):
    enabled: bool = True
    start: str = Field(default="23:00", description="HH:MM")
    end: str = Field(default="06:00", description="HH:MM")
    behavior: str = Field(
        default="hold",
        description="'hold' (send later) | 'drop' (skip) | 'send' (ignore quiet hours)",
    )


class NotificationCondition(BobiModel):
    label: str
    detail: str | None = None


class NotificationRule(BobiModel):
    id: str
    name: str
    description: str
    icon: str = "bell"
    enabled: bool = True
    recipients: list[str] = Field(default_factory=list, description="User display names.")
    lead_time_minutes: int | None = Field(
        default=None,
        description="For 'before the event' style rules.",
    )
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    conditions: list[NotificationCondition] = Field(default_factory=list)
    frequency: str = Field(default="event", description="'event' | 'hourly' | 'daily'")
    cooldown_minutes: int = 0
    last_triggered: datetime | None = None
    trigger_count_7d: int = 0
    advanced: Advanced = Field(default_factory=Advanced)


class NotificationList(BobiModel):
    rules: list[NotificationRule]
