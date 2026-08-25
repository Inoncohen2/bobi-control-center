"""Devices — friendly smart-home objects, not Home Assistant entities."""

from __future__ import annotations

from pydantic import Field

from .common import Advanced, BobiModel, DeviceCategory


class RawEntity(BobiModel):
    """The shape an adapter returns before the service layer humanises it.

    This is intentionally the *only* place where Home Assistant vocabulary is
    allowed to appear, and it never reaches the frontend as-is.
    """

    entity_id: str
    friendly_name: str
    state: str
    available: bool = True
    area: str | None = None
    integration: str | None = None
    attributes: dict[str, object] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)


class Device(BobiModel):
    id: str
    display_name: str
    room: str
    category: DeviceCategory
    state: str = Field(description="Bobi-level state, e.g. 'on' | 'off' | 'unavailable'.")
    state_label: str = Field(default="", description="Hebrew label for the state.")
    available: bool = True
    aliases: list[str] = Field(
        default_factory=list,
        description="Names Bobi understands when spoken or written.",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="e.g. 'turn_on' | 'turn_off' | 'set_temperature'.",
    )
    icon: str = "plug"
    advanced: Advanced = Field(default_factory=Advanced)


class DeviceList(BobiModel):
    devices: list[Device]
    rooms: list[str]
    categories: list[DeviceCategory]
