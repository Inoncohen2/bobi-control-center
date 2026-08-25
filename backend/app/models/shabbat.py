"""Shabbat clock — the most product-heavy screen in the application."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import Advanced, BobiModel


class TimeRange(BobiModel):
    """A single on/off window for a device during Shabbat.

    ``crosses_midnight`` is derived server-side (see ``ShabbatService``) so the
    frontend never has to re-implement the comparison, and both agree.
    """

    id: str
    start: str = Field(description="HH:MM")
    end: str = Field(description="HH:MM")
    crosses_midnight: bool = False
    enabled: bool = True
    day: str = Field(default="friday", description="'friday' | 'saturday'")


class ShabbatDeviceSchedule(BobiModel):
    id: str
    device_id: str
    device_name: str
    room: str
    icon: str = "lightbulb"
    enabled: bool = True
    ranges: list[TimeRange] = Field(default_factory=list)
    note: str | None = None
    advanced: Advanced = Field(default_factory=Advanced)


class ShabbatTemplate(BobiModel):
    id: str
    name: str
    description: str
    created_at: datetime
    schedules: list[ShabbatDeviceSchedule] = Field(default_factory=list)


class ShabbatTimes(BobiModel):
    """Candle-lighting / havdalah times. Mock values in Phase 1."""

    parasha: str
    candle_lighting: str = Field(description="HH:MM")
    havdalah: str = Field(description="HH:MM")
    friday_date: str
    saturday_date: str
    city: str = "תל אביב"


class ShabbatConfig(BobiModel):
    enabled: bool = True
    times: ShabbatTimes
    schedules: list[ShabbatDeviceSchedule] = Field(default_factory=list)
    templates: list[ShabbatTemplate] = Field(default_factory=list)
    active_template_id: str | None = None
    updated_at: datetime | None = None
    has_draft: bool = False


class ShabbatDraft(BobiModel):
    """What the UI sends for preview/confirm. Never applied directly."""

    enabled: bool = True
    schedules: list[ShabbatDeviceSchedule] = Field(default_factory=list)
    active_template_id: str | None = None


class SaveTemplateRequest(BobiModel):
    name: str
    description: str = ""
    schedules: list[ShabbatDeviceSchedule] = Field(default_factory=list)
