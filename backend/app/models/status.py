"""System status, dashboard statistics and the activity timeline."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import BobiModel, HealthState, Severity


class ComponentHealth(BobiModel):
    """One health card on the dashboard, e.g. 'WhatsApp / מחובר'."""

    id: str
    name: str
    state: HealthState
    label: str = Field(description="Hebrew, human-readable state, e.g. 'מחובר'.")
    detail: str | None = None


class StatItem(BobiModel):
    id: str
    label: str
    value: int
    hint: str | None = None
    severity: Severity = Severity.OK


class ActivityEntry(BobiModel):
    id: str
    time: str = Field(description="HH:MM, already localised for display.")
    timestamp: datetime
    title: str
    detail: str | None = None
    icon: str = "activity"
    severity: Severity = Severity.OK


class AttentionItem(BobiModel):
    """A dashboard warning phrased for a human, not for an engineer."""

    id: str
    title: str
    description: str
    severity: Severity = Severity.WARNING
    component: str | None = None
    technical_details: str | None = None
    action_label: str | None = None
    action_href: str | None = None


class SystemStatus(BobiModel):
    name: str = "בובי"
    version: str
    adapter: str = Field(description="'mock' or 'real' — which adapter is serving data.")
    read_only: bool = Field(
        default=True,
        description="True while no write can reach Home Assistant.",
    )
    generated_at: datetime
    components: list[ComponentHealth] = Field(default_factory=list)
    stats: list[StatItem] = Field(default_factory=list)
    activity: list[ActivityEntry] = Field(default_factory=list)
    attention: list[AttentionItem] = Field(default_factory=list)
