"""Capabilities — the things Bobi knows how to do."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import Advanced, BobiModel, HealthState


class CapabilitySetting(BobiModel):
    """A single tunable exposed on a capability's detail screen."""

    key: str
    label: str
    type: str = Field(description="'bool' | 'text' | 'select' | 'time_range' | 'number'")
    value: object | None = None
    options: list[str] = Field(default_factory=list)
    help: str | None = None


class Capability(BobiModel):
    id: str
    name: str
    description: str
    icon: str
    group: str = Field(description="Hebrew grouping, e.g. 'שליטה בבית'.")
    enabled: bool = True
    state: HealthState = HealthState.ONLINE
    state_label: str = "פעיל"
    warning: str | None = None
    settings: list[CapabilitySetting] = Field(default_factory=list)
    related_device_ids: list[str] = Field(default_factory=list)
    last_used: datetime | None = None
    advanced: Advanced = Field(default_factory=Advanced)


class CapabilityToggleRequest(BobiModel):
    enabled: bool
