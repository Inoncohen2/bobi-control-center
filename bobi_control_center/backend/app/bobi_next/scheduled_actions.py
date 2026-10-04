"""Scheduled device-action contracts for Bobi Next.

A delayed command stores *intent*, not a stale HA service plan. Stable Bobi
device ids are captured when the user creates the schedule. At execution time
Bobi rediscovers HA, rechecks policy/capabilities and builds a fresh plan from
live state. This is essential for relative commands such as "+0.5 degree".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .models import ActionPlan, DeviceRecord, TargetResolution
from .planner import build_plan
from .routing import RoutedIntent


@dataclass(slots=True, frozen=True)
class ScheduledDeviceAction:
    schema_version: int
    source_text: str
    device_ids: tuple[str, ...]
    domain_hint: str
    capability: str
    operation: str
    value: Any = None
    delta: float | None = None
    requires_confirmation: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = "device_action"
        payload["device_ids"] = list(self.device_ids)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ScheduledDeviceAction:
        if payload.get("type") != "device_action":
            raise ValueError("unsupported_scheduled_payload")
        if int(payload.get("schema_version", 0)) != 1:
            raise ValueError("unsupported_scheduled_schema")
        device_ids = payload.get("device_ids")
        valid_ids = isinstance(device_ids, list) and all(
            isinstance(item, str) for item in device_ids
        )
        if not valid_ids:
            raise ValueError("invalid_scheduled_device_ids")
        if not device_ids:
            raise ValueError("scheduled_target_required")
        return cls(
            schema_version=1,
            source_text=str(payload.get("source_text", "")),
            device_ids=tuple(device_ids),
            domain_hint=str(payload.get("domain_hint", "")),
            capability=str(payload.get("capability", "")),
            operation=str(payload.get("operation", "")),
            value=payload.get("value"),
            delta=(
                float(payload["delta"])
                if payload.get("delta") is not None
                else None
            ),
            requires_confirmation=bool(payload.get("requires_confirmation", False)),
        )


def capture_scheduled_action(
    *,
    source_text: str,
    routed: RoutedIntent,
    resolution: TargetResolution,
    requires_confirmation: bool = False,
) -> ScheduledDeviceAction:
    if not routed.defer_execution:
        raise ValueError("intent_is_not_deferred")
    if not resolution.ok or not resolution.devices:
        raise ValueError("scheduled_target_unresolved")
    return ScheduledDeviceAction(
        schema_version=1,
        source_text=source_text,
        device_ids=tuple(device.bobi_id for device in resolution.devices),
        domain_hint=routed.domain_hint,
        capability=routed.capability,
        operation=routed.operation,
        value=routed.value,
        delta=routed.delta,
        requires_confirmation=requires_confirmation,
    )


def build_due_plans(
    action: ScheduledDeviceAction,
    devices: Iterable[DeviceRecord],
    *,
    request_id: str,
) -> tuple[ActionPlan, ...]:
    """Build fresh plans from the current discovered device snapshot."""

    by_id = {device.bobi_id: device for device in devices}
    selected: list[DeviceRecord] = []
    for device_id in action.device_ids:
        device = by_id.get(device_id)
        if device is None:
            raise ValueError(f"scheduled_device_missing:{device_id}")
        if action.capability not in device.capabilities:
            raise ValueError(f"scheduled_capability_missing:{device_id}:{action.capability}")
        selected.append(device)

    plans = tuple(
        build_plan(
            request_id=request_id,
            device=device,
            capability=action.capability,
            operation=action.operation,
            value=action.value,
            delta=action.delta,
            source="direct",
            confidence=1.0,
        )
        for device in selected
    )
    if action.requires_confirmation:
        for plan in plans:
            plan.requires_confirmation = True
    return plans
