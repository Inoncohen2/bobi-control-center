"""Capture conditional rules from semantic intent against live HA discovery.

The understanding layer describes the trigger in human-semantic fields.  This
module is the authority that binds that description to one currently discovered
HA entity and persists a stable identity that survives entity_id renames.
"""

from __future__ import annotations

from typing import Any

from .authorization import RequestProvenance
from .conditional import ConditionalRule, ConditionalRuleStore, TriggerSpec, trigger_ref
from .intent import SemanticIntent
from .models import DeviceRecord, EntityRecord, TargetResolution
from .resolver import resolve_target
from .routing import RoutedIntent
from .scheduled_actions import capture_scheduled_action


def _synthetic_devices(devices: tuple[DeviceRecord, ...]) -> tuple[DeviceRecord, ...]:
    flattened: list[DeviceRecord] = []
    for parent in devices:
        for entity in parent.entities:
            name = entity.name or parent.name or entity.entity_id
            aliases = tuple(dict.fromkeys((*entity.aliases, parent.name, *parent.aliases)))
            flattened.append(
                DeviceRecord(
                    bobi_id=f"trigger:{entity.entity_id}",
                    stable_key=f"trigger:{entity.entity_id}",
                    ha_device_id=entity.device_id,
                    name=name,
                    area_id=entity.area_id or parent.area_id,
                    area_name=entity.area_name or parent.area_name,
                    aliases=tuple(alias for alias in aliases if alias),
                    entities=(entity,),
                    available=entity.available,
                )
            )
    return tuple(flattened)


def resolve_trigger_entity(
    payload: dict[str, Any],
    devices: tuple[DeviceRecord, ...],
) -> EntityRecord:
    target_text = str(payload.get("target_text") or "").strip()
    if not target_text:
        raise ValueError("conditional_trigger_target_missing")
    domain_hint = str(payload.get("domain_hint") or "").strip()
    resolution = resolve_target(
        target_text,
        _synthetic_devices(devices),
        domain_hint=domain_hint,
    )
    if not resolution.ok or len(resolution.devices) != 1:
        raise ValueError(f"conditional_trigger_{resolution.reason}")
    entity = resolution.devices[0].entities[0]
    if not entity.available:
        raise ValueError("conditional_trigger_unavailable")
    return entity


def capture_trigger(
    payload: dict[str, Any],
    devices: tuple[DeviceRecord, ...],
) -> TriggerSpec:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("conditional_payload_missing")
    entity = resolve_trigger_entity(payload, devices)
    kind = str(payload.get("kind") or "state").strip().casefold()
    if kind not in {"state", "numeric", "availability"}:
        raise ValueError("unsupported_trigger_kind")

    attribute = str(payload.get("attribute") or "").strip()
    from_state = payload.get("from_state")
    to_state = payload.get("to_state")
    above = payload.get("above")
    below = payload.get("below")
    for_seconds = max(0, int(payload.get("for_seconds", 0) or 0))

    if kind == "numeric":
        if above is None and below is None:
            raise ValueError("numeric_trigger_threshold_missing")
        above = float(above) if above is not None else None
        below = float(below) if below is not None else None
        if above is not None and below is not None and below >= above:
            raise ValueError("numeric_trigger_invalid_window")
    elif above is not None or below is not None:
        raise ValueError("threshold_only_valid_for_numeric_trigger")

    if kind == "availability" and to_state not in {"available", "unavailable", None}:
        raise ValueError("invalid_availability_target")

    return TriggerSpec(
        kind=kind,  # type: ignore[arg-type]
        entity=trigger_ref(entity),
        attribute=attribute,
        from_state=str(from_state) if from_state is not None else None,
        to_state=str(to_state) if to_state is not None else None,
        above=above,
        below=below,
        for_seconds=for_seconds,
    )


def persist_conditional_rule(
    store: ConditionalRuleStore,
    *,
    request_id: str,
    user_key: str,
    source_text: str,
    intent: SemanticIntent,
    routed: RoutedIntent,
    action_resolution: TargetResolution,
    provenance: RequestProvenance,
    devices: tuple[DeviceRecord, ...],
    now_ts: int,
) -> ConditionalRule:
    if not intent.conditional or routed.defer_reason != "conditional":
        raise ValueError("intent_is_not_conditional")

    trigger = capture_trigger(intent.condition_payload, devices)
    action = capture_scheduled_action(
        source_text=source_text,
        routed=routed,
        resolution=action_resolution,
        provenance=provenance,
    )
    payload = intent.condition_payload
    return store.create(
        rule_id=f"req-{request_id}",
        user_key=user_key,
        source_text=source_text,
        trigger=trigger,
        action_payload=action.to_payload(),
        cooldown_seconds=max(0, int(payload.get("cooldown_seconds", 0) or 0)),
        once=bool(payload.get("once", False)),
        now_ts=now_ts,
    )
