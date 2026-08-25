"""Bobi automations — never native Home Assistant automation YAML."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from .common import Advanced, AutomationType, BobiModel, Source


class AutomationTarget(BobiModel):
    id: str
    name: str
    room: str | None = None


class AutomationAction(BobiModel):
    type: str = Field(description="'turn_on' | 'turn_off' | 'set_temperature' | 'notify'…")
    label: str = Field(description="Hebrew verb phrase, e.g. 'להדליק'.")
    value: object | None = None


class AutomationCondition(BobiModel):
    type: str = Field(description="'presence' | 'sun' | 'temperature' | 'device_state'…")
    label: str
    operator: str | None = None
    value: object | None = None


class Automation(BobiModel):
    id: str
    name: str
    enabled: bool = True
    automation_type: AutomationType
    targets: list[AutomationTarget] = Field(default_factory=list)
    actions: list[AutomationAction] = Field(default_factory=list)
    days: list[int] = Field(
        default_factory=list,
        description="0=Sunday … 6=Saturday, matching the Hebrew week.",
    )
    start_time: str | None = Field(default=None, description="HH:MM")
    end_time: str | None = Field(default=None, description="HH:MM")
    times: list[str] = Field(default_factory=list, description="For multi_time automations.")
    run_date: date | None = Field(default=None, description="For one_time automations.")
    conditions: list[AutomationCondition] = Field(default_factory=list)
    owner: str | None = None
    created_by: str | None = None
    source: Source = Source.WEB
    last_triggered: datetime | None = None
    crosses_midnight: bool = False
    summary: str = Field(default="", description="Human-readable one-line description.")
    advanced: Advanced = Field(default_factory=Advanced)


class AutomationDraft(BobiModel):
    """What the wizard submits. ``id`` is absent when creating."""

    id: str | None = None
    name: str
    enabled: bool = True
    automation_type: AutomationType
    targets: list[AutomationTarget] = Field(default_factory=list)
    actions: list[AutomationAction] = Field(default_factory=list)
    days: list[int] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    times: list[str] = Field(default_factory=list)
    run_date: date | None = None
    conditions: list[AutomationCondition] = Field(default_factory=list)
    owner: str | None = None


class AutomationList(BobiModel):
    automations: list[Automation]
