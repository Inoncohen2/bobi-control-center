"""Scheduled device-action contracts for Bobi Next.

A delayed command stores *intent* and its execution authority, not a stale HA
service plan. Stable Bobi device ids are captured when the user creates the
schedule. At execution time Bobi rediscovers HA, rechecks policy/capabilities
and builds a fresh plan from live state. This is essential for relative
commands such as "+0.5 degree" and for preserving context authority safely.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .authorization import RequestProvenance
from .models import ActionPlan, DeviceRecord, TargetResolution
from .planner import build_plan
from .routing import RoutedIntent

_CURRENT_SCHEMA = 2
_VALID_SOURCE_KINDS = {"direct", "context", "clarification", "instinct", "ai"}


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
    provenance_source_kind: str = "legacy"
    provenance_same_text: bool = False
    provenance_explicit_device_ids: tuple[str, ...] = ()
    provenance_allowed_device_ids: tuple[str, ...] = ()
    provenance_reference_only: bool = True
    provenance_question: bool = False
    provenance_negated: bool = False
    provenance_literal_name: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = "device_action"
        payload["device_ids"] = list(self.device_ids)
        payload["provenance_explicit_device_ids"] = list(
            self.provenance_explicit_device_ids
        )
        payload["provenance_allowed_device_ids"] = list(
            self.provenance_allowed_device_ids
        )
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ScheduledDeviceAction:
        if payload.get("type") != "device_action":
            raise ValueError("unsupported_scheduled_payload")
        version = int(payload.get("schema_version", 0))
        if version not in {1, _CURRENT_SCHEMA}:
            raise ValueError("unsupported_scheduled_schema")
        device_ids = _read_ids(payload, "device_ids", required=True)

        common = {
            "source_text": str(payload.get("source_text", "")),
            "device_ids": device_ids,
            "domain_hint": str(payload.get("domain_hint", "")),
            "capability": str(payload.get("capability", "")),
            "operation": str(payload.get("operation", "")),
            "value": payload.get("value"),
            "delta": (
                float(payload["delta"])
                if payload.get("delta") is not None
                else None
            ),
            "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        }
        if version == 1:
            # Bobi Next has never shipped this schema. Treat any development-era
            # v1 job as untrusted legacy provenance instead of silently granting
            # the "direct" authority the old runner used to invent at run time.
            return cls(schema_version=1, **common)

        source_kind = str(payload.get("provenance_source_kind", "")).strip()
        if source_kind not in _VALID_SOURCE_KINDS:
            raise ValueError("invalid_scheduled_provenance_source")
        return cls(
            schema_version=_CURRENT_SCHEMA,
            **common,
            provenance_source_kind=source_kind,
            provenance_same_text=bool(payload.get("provenance_same_text", False)),
            provenance_explicit_device_ids=_read_ids(
                payload,
                "provenance_explicit_device_ids",
            ),
            provenance_allowed_device_ids=_read_ids(
                payload,
                "provenance_allowed_device_ids",
            ),
            provenance_reference_only=bool(
                payload.get("provenance_reference_only", False)
            ),
            provenance_question=bool(payload.get("provenance_question", False)),
            provenance_negated=bool(payload.get("provenance_negated", False)),
            provenance_literal_name=bool(
                payload.get("provenance_literal_name", False)
            ),
        )


def _read_ids(
    payload: dict[str, Any],
    key: str,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    raw = payload.get(key, [])
    if not isinstance(raw, list):
        raise ValueError(f"invalid_scheduled_{key}")
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"invalid_scheduled_{key}")
    if required and not raw:
        raise ValueError("scheduled_target_required")
    return tuple(raw)


def _stable_ids_for(
    target_ids: frozenset[str],
    devices: tuple[DeviceRecord, ...],
) -> tuple[str, ...]:
    stable: list[str] = []
    for device in devices:
        keys = {device.bobi_id, *(entity.entity_id for entity in device.entities)}
        if target_ids.intersection(keys):
            stable.append(device.bobi_id)
    return tuple(stable)


def _resolved_keys(devices: tuple[DeviceRecord, ...]) -> frozenset[str]:
    keys: set[str] = set()
    for device in devices:
        keys.add(device.bobi_id)
        keys.update(entity.entity_id for entity in device.entities)
    return frozenset(keys)


def capture_scheduled_action(
    *,
    source_text: str,
    routed: RoutedIntent,
    resolution: TargetResolution,
    provenance: RequestProvenance | None = None,
    requires_confirmation: bool = False,
) -> ScheduledDeviceAction:
    if not routed.defer_execution:
        raise ValueError("intent_is_not_deferred")
    if not resolution.ok or not resolution.devices:
        raise ValueError("scheduled_target_unresolved")

    devices = tuple(resolution.devices)
    if provenance is None:
        # Missing authority metadata is allowed to persist only in a fail-closed
        # form. The due runner will require approval rather than inventing it.
        provenance = RequestProvenance(
            source_kind="direct",
            same_text=False,
            reference_only=True,
        )
    if provenance.negated:
        raise ValueError("scheduled_source_negated")
    if provenance.literal_name:
        raise ValueError("scheduled_literal_name_protected")
    if provenance.source_kind not in _VALID_SOURCE_KINDS:
        raise ValueError("invalid_scheduled_provenance_source")

    resolved_keys = _resolved_keys(devices)
    if provenance.explicit_target_ids and not provenance.explicit_target_ids.issubset(
        resolved_keys
    ):
        raise ValueError("scheduled_provenance_target_mismatch")

    return ScheduledDeviceAction(
        schema_version=_CURRENT_SCHEMA,
        source_text=source_text,
        device_ids=tuple(device.bobi_id for device in devices),
        domain_hint=routed.domain_hint,
        capability=routed.capability,
        operation=routed.operation,
        value=routed.value,
        delta=routed.delta,
        requires_confirmation=requires_confirmation,
        provenance_source_kind=provenance.source_kind,
        provenance_same_text=provenance.same_text,
        provenance_explicit_device_ids=_stable_ids_for(
            provenance.explicit_target_ids,
            devices,
        ),
        provenance_allowed_device_ids=_stable_ids_for(
            provenance.allowed_target_ids,
            devices,
        ),
        provenance_reference_only=provenance.reference_only,
        provenance_question=provenance.question,
        provenance_negated=provenance.negated,
        provenance_literal_name=provenance.literal_name,
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

    plan_source = (
        action.provenance_source_kind
        if action.provenance_source_kind in _VALID_SOURCE_KINDS
        else "direct"
    )
    plans = tuple(
        build_plan(
            request_id=request_id,
            device=device,
            capability=action.capability,
            operation=action.operation,
            value=action.value,
            delta=action.delta,
            source=plan_source,
            confidence=1.0,
        )
        for device in selected
    )
    if action.requires_confirmation:
        for plan in plans:
            plan.requires_confirmation = True
    return plans
