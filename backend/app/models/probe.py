"""The probe pipeline — Bobi's Test Center.

Everything here is *probe only*: ``would_execute`` is hard-coded to ``False``
and no code path in this module can reach a device.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from .common import BobiModel


class ProbeFamily(str, Enum):
    SCHEDULE = "schedule"
    CONTROL = "control"
    QUERY = "query"
    TASK = "task"
    CALENDAR = "calendar"
    NOTIFICATION = "notification"
    SHABBAT = "shabbat"
    UNKNOWN = "unknown"


class ProbeTarget(BobiModel):
    id: str | None = None
    name: str | None = None
    room: str | None = None
    matched_alias: str | None = None
    confidence: float = 0.0


class ProbeSchedule(BobiModel):
    kind: str = Field(description="'one_time' | 'daily' | 'weekly' | 'immediate'")
    time: str | None = None
    date: str | None = None
    days: list[int] = Field(default_factory=list)
    description: str = ""


class ProbeStep(BobiModel):
    """One node in the visual pipeline rendered by the Test Center."""

    id: str
    label: str
    status: str = Field(default="ok", description="'ok' | 'warning' | 'skipped' | 'failed'")
    value: str | None = None
    detail: str | None = None


class ProbeRequest(BobiModel):
    text: str = Field(min_length=1, max_length=1000)


class ProbeResult(BobiModel):
    original_text: str
    normalized_text: str
    family: ProbeFamily
    domain: str | None = None
    action: str | None = None
    target: ProbeTarget = Field(default_factory=ProbeTarget)
    schedule: ProbeSchedule | None = None
    skill: str | None = None
    safe: bool = True
    would_execute: bool = Field(
        default=False,
        description="Always False. The probe endpoint never executes anything.",
    )
    warnings: list[str] = Field(default_factory=list)
    steps: list[ProbeStep] = Field(default_factory=list)
    confidence: float = 0.0
    duration_ms: int = 0


class ProbeHistoryEntry(BobiModel):
    id: str
    text: str
    family: ProbeFamily
    summary: str
    timestamp: datetime
    safe: bool = True


class ProbeHistory(BobiModel):
    entries: list[ProbeHistoryEntry]
