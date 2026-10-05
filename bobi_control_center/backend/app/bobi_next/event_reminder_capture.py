"""Deterministic capture of semantic event-reminder intents.

The understanding layer may describe a trigger in semantic terms, but this
module binds that description to live discovered Home Assistant identity. Raw
entity ids from AI payloads are never trusted as authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .authorization import UserPolicy
from .conditional import TriggerSpec, entity_stable_key, trigger_ref
from .event_reminders import EventReminderDefinition, EventReminderStore
from .intent import SemanticIntent
from .models import DeviceRecord, EntityRecord, TargetResolution
from .resolver import resolve_target

AliasProvider = Callable[[str], Iterable[tuple[str, float]]]

_SELF_TARGETS = frozenset(
    {
        "i",
        "me",
        "myself",
        "my location",
        "אני",
        "אותי",
        "המיקום שלי",
        "מיקום שלי",
    }
)
_PRESENCE_DOMAINS = frozenset({"", "person", "device_tracker"})


@dataclass(slots=True, frozen=True)
class EventReminderCaptureResult:
    outcome: str
    reason: str
    trigger_id: str = ""
    resolution: TargetResolution | None = None
    definition: EventReminderDefinition | None = None
    metadata: dict[str, Any] | None = None


def event_reminder_trigger_id(request_id: str) -> str:
    digest = hashlib.sha256(str(request_id).encode()).hexdigest()[:32]
    return f"event-rem-{digest}"


def _policy_reason(policy: UserPolicy) -> str:
    capability = "reminder.create"
    if "*" not in policy.allowed_capabilities and capability not in policy.allowed_capabilities:
        return "capability_not_allowed"
    if capability in policy.denied_capabilities:
        return "capability_denied"
    if "*" not in policy.allowed_domains and "reminder" not in policy.allowed_domains:
        return "domain_not_allowed"
    if capability in policy.denied_actions:
        return "action_denied"
    return ""


def _one_trigger_entity(device: DeviceRecord, domain: str) -> EntityRecord:
    candidates = tuple(
        entity for entity in device.entities if not domain or entity.domain == domain
    )
    if not candidates:
        raise ValueError("event_reminder_trigger_entity_missing")
    if len(candidates) != 1:
        raise ValueError("event_reminder_trigger_entity_ambiguous")
    return candidates[0]


def _is_self_target(value: str) -> bool:
    normalized = " ".join(value.casefold().strip().split())
    return normalized in _SELF_TARGETS


def _presence_resolution(
    devices: tuple[DeviceRecord, ...],
    presence_entity: EntityRecord | None,
) -> tuple[TargetResolution, EntityRecord | None]:
    if presence_entity is None:
        return TargetResolution(False, reason="presence_binding_required"), None
    stable_key = entity_stable_key(presence_entity)
    matches = tuple(
        device
        for device in devices
        if any(entity_stable_key(entity) == stable_key for entity in device.entities)
    )
    if len(matches) != 1:
        return TargetResolution(False, reason="presence_binding_unavailable"), None
    live = next(
        entity
        for entity in matches[0].entities
        if entity_stable_key(entity) == stable_key
    )
    if live.domain not in {"person", "device_tracker"}:
        return TargetResolution(False, reason="presence_binding_invalid"), None
    return (
        TargetResolution(
            True,
            devices=(matches[0],),
            confidence=1.0,
            reason="presence_binding",
            resolution_kind="presence_binding",
            candidate_ids=(matches[0].bobi_id,),
        ),
        live,
    )


def _trigger_spec(payload: dict[str, Any], entity: EntityRecord) -> TriggerSpec:
    kind = str(payload.get("kind") or "").strip().casefold()
    if kind not in {"state", "numeric", "availability"}:
        raise ValueError("event_reminder_trigger_kind_invalid")

    from_state = payload.get("from_state")
    to_state = payload.get("to_state")
    attribute = str(payload.get("attribute") or "").strip()
    above = payload.get("above")
    below = payload.get("below")
    for_seconds = max(0, int(payload.get("for_seconds", 0) or 0))
    if for_seconds:
        raise ValueError("event_reminder_duration_not_supported")

    if kind == "state":
        if from_state is None and to_state is None:
            raise ValueError("event_reminder_state_transition_required")
        return TriggerSpec(
            kind="state",
            entity=trigger_ref(entity),
            attribute=attribute,
            from_state=str(from_state) if from_state is not None else None,
            to_state=str(to_state) if to_state is not None else None,
        )

    if kind == "availability":
        normalized = str(to_state or "").strip().casefold()
        if normalized not in {"available", "unavailable"}:
            raise ValueError("event_reminder_availability_state_invalid")
        return TriggerSpec(
            kind="availability",
            entity=trigger_ref(entity),
            to_state=normalized,
        )

    if above is None and below is None:
        raise ValueError("event_reminder_numeric_threshold_required")
    return TriggerSpec(
        kind="numeric",
        entity=trigger_ref(entity),
        attribute=attribute,
        above=float(above) if above is not None else None,
        below=float(below) if below is not None else None,
    )


def capture_event_reminder(
    *,
    request_id: str,
    user_key: str,
    provider_key: str,
    chat_id: str,
    source_message_id: str,
    intent: SemanticIntent,
    devices: Iterable[DeviceRecord],
    policy: UserPolicy,
    store: EventReminderStore,
    learned_aliases: AliasProvider | None = None,
    presence_entity: EntityRecord | None = None,
    now_ts: int,
    dry_run: bool = False,
) -> EventReminderCaptureResult:
    """Validate, resolve and persist one conditional reminder definition."""

    if intent.family.casefold() != "reminder" and intent.canonical_domain != "reminder":
        return EventReminderCaptureResult("unsupported", "not_reminder")
    if intent.canonical_operation != "create":
        return EventReminderCaptureResult("unsupported", "unsupported_reminder_operation")
    if intent.negated:
        return EventReminderCaptureResult("ignored", "source_negated")
    if bool(intent.metadata.get("question", False)):
        return EventReminderCaptureResult("ignored", "source_question")
    if not intent.conditional:
        return EventReminderCaptureResult("unsupported", "not_conditional_reminder")
    if intent.scheduled:
        return EventReminderCaptureResult("clarification", "reminder_time_and_event_conflict")
    if policy.user_key != user_key:
        return EventReminderCaptureResult("blocked", "policy_user_mismatch")
    blocked = _policy_reason(policy)
    if blocked:
        return EventReminderCaptureResult("blocked", blocked)
    if not provider_key.strip() or not chat_id.strip():
        return EventReminderCaptureResult("failed", "reminder_delivery_target_missing")

    reminder_text = str(
        intent.target_text or intent.metadata.get("reminder_text") or ""
    ).strip()
    if not reminder_text:
        return EventReminderCaptureResult("clarification", "reminder_text_missing")

    payload = intent.condition_payload
    if not isinstance(payload, dict):
        return EventReminderCaptureResult("clarification", "event_reminder_condition_missing")
    trigger_target = str(payload.get("trigger_target_text") or "").strip()
    trigger_domain = str(payload.get("trigger_domain") or "").strip().casefold()
    if not trigger_target:
        return EventReminderCaptureResult("clarification", "event_reminder_trigger_target_missing")

    device_tuple = tuple(devices)
    bound_entity: EntityRecord | None = None
    if _is_self_target(trigger_target):
        if trigger_domain not in _PRESENCE_DOMAINS:
            return EventReminderCaptureResult(
                "clarification",
                "presence_trigger_domain_invalid",
            )
        resolution, bound_entity = _presence_resolution(device_tuple, presence_entity)
    else:
        resolution = resolve_target(
            trigger_target,
            device_tuple,
            domain_hint=trigger_domain,
            learned_aliases=learned_aliases,
            allow_group=False,
        )

    if not resolution.ok or len(resolution.devices) != 1:
        return EventReminderCaptureResult(
            "clarification",
            resolution.reason or "event_reminder_trigger_ambiguous",
            resolution=resolution,
        )

    try:
        entity = bound_entity or _one_trigger_entity(resolution.devices[0], trigger_domain)
        trigger = _trigger_spec(payload, entity)
    except (TypeError, ValueError) as exc:
        return EventReminderCaptureResult(
            "clarification",
            str(exc),
            resolution=resolution,
        )

    trigger_id = event_reminder_trigger_id(request_id)
    once = bool(payload.get("once", True))
    cooldown = max(0, int(payload.get("cooldown_seconds", 0) or 0))
    metadata = {
        "trigger_id": trigger_id,
        "trigger_stable_key": trigger.entity.stable_key,
        "trigger_kind": trigger.kind,
        "once": once,
        "cooldown_seconds": cooldown,
    }
    if dry_run:
        return EventReminderCaptureResult(
            "shadow",
            "dry_run",
            trigger_id=trigger_id,
            resolution=resolution,
            metadata=metadata,
        )

    try:
        definition = store.create(
            trigger_id=trigger_id,
            user_key=user_key,
            provider_key=provider_key,
            chat_id=chat_id,
            text=reminder_text,
            trigger=trigger,
            once=once,
            cooldown_seconds=cooldown,
            source_message_id=source_message_id,
            now_ts=now_ts,
        )
    except ValueError as exc:
        if str(exc) != "duplicate_event_reminder_id":
            raise
        definition = store.get(trigger_id)
        if definition is None:
            raise RuntimeError("event_reminder_duplicate_missing") from exc

    return EventReminderCaptureResult(
        "created",
        "event_reminder_created",
        trigger_id=trigger_id,
        resolution=resolution,
        definition=definition,
        metadata=metadata,
    )
