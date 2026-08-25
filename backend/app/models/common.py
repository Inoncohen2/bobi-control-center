"""Shared primitives used across every Bobi domain model."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BobiModel(BaseModel):
    """Base model for the whole domain.

    ``populate_by_name`` lets us keep pythonic field names while still
    accepting the exact JSON shape the frontend sends back.
    """

    model_config = ConfigDict(populate_by_name=True, use_enum_values=False)


class Severity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class HealthState(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class Source(str, Enum):
    """Where a change or an event originated from."""

    WEB = "web"
    WHATSAPP = "whatsapp"
    AUTOMATION = "automation"
    SYSTEM = "system"


class DeviceCategory(str, Enum):
    LIGHT = "light"
    CLIMATE = "climate"
    CAMERA = "camera"
    COVER = "cover"
    SWITCH = "switch"
    BOILER = "boiler"
    VACUUM = "vacuum"
    SENSOR = "sensor"


class AutomationType(str, Enum):
    ONE_TIME = "one_time"
    DAILY = "daily"
    WEEKLY = "weekly"
    TIME_WINDOW = "time_window"
    MULTI_TIME = "multi_time"
    CONDITIONAL = "conditional"
    SMART_NOTIFICATION = "smart_notification"


class Advanced(BobiModel):
    """Technical detail deliberately hidden behind an 'Advanced' disclosure.

    The frontend must never branch on the contents of this object — it may only
    display it inside an advanced/technical panel.
    """

    entity_id: str | None = None
    object_id: str | None = None
    integration: str | None = None
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, object] = Field(default_factory=dict)


class PreviewLine(BobiModel):
    """One human-readable line of a change preview."""

    text: str
    emphasis: bool = False


class ChangePreview(BobiModel):
    """The 'Preview' step of the Preview → Confirm → Execute safety model."""

    summary: str
    lines: list[PreviewLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    destructive: bool = False
    token: str = Field(
        description="Opaque token echoed back on confirm so a preview cannot be skipped.",
    )


class OperationResult(BobiModel):
    """The 'Result' step of the safety model."""

    success: bool
    message: str
    dry_run: bool = Field(
        default=True,
        description="Phase 1 is always a dry run: nothing reaches Home Assistant.",
    )
    applied: bool = False
    audit_id: str | None = None
