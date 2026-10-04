"""Deterministic Calendar/To-do orchestration for Bobi Next.

Language understanding may describe a productivity intent, but this module owns
resource resolution, permission checks and the fixed adapter operation. It never
accepts an arbitrary Home Assistant domain/action pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .authorization import RequestProvenance, UserPolicy, authorize_plan
from .ha_productivity import CalendarAdapter, TodoAdapter
from .intent import SemanticIntent
from .models import ActionPlan, DeviceRecord, EntityRecord, TargetResolution
from .resolver import resolve_target

_READ_OPERATIONS = {"get", "read", "query", "status", "list"}
_CALENDAR_CREATE = {"add", "create", "create_event"}
_TODO_ADD = {"add", "create", "add_item"}
_TODO_UPDATE = {"update", "update_item", "complete", "uncomplete", "rename"}
_TODO_REMOVE = {"remove", "delete", "remove_item"}
_TODO_CLEAR = {"clear_completed", "remove_completed", "remove_completed_items"}


@dataclass(slots=True, frozen=True)
class ProductivityResult:
    outcome: str
    reason: str
    domain: str
    operation: str
    entity_id: str = ""
    resolution: TargetResolution | None = None
    payload: Any = None
    plans: tuple[ActionPlan, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def _resource_devices(
    devices: tuple[DeviceRecord, ...],
    domain: str,
) -> tuple[DeviceRecord, ...]:
    resources: list[DeviceRecord] = []
    for parent in devices:
        for entity in parent.entities:
            if entity.domain != domain:
                continue
            name = entity.name or parent.name or entity.entity_id
            aliases = tuple(
                dict.fromkeys(
                    alias
                    for alias in (*entity.aliases, parent.name, *parent.aliases)
                    if alias
                )
            )
            resources.append(
                DeviceRecord(
                    bobi_id=f"resource:{entity.entity_id}",
                    stable_key=(
                        f"resource:{entity.platform}:{entity.unique_id}"
                        if entity.platform and entity.unique_id
                        else f"resource:{entity.entity_id}"
                    ),
                    ha_device_id=entity.device_id,
                    name=name,
                    area_id=entity.area_id or parent.area_id,
                    area_name=entity.area_name or parent.area_name,
                    aliases=aliases,
                    entities=(entity,),
                    available=entity.available,
                )
            )
    return tuple(resources)


def _entity_from_resolution(resolution: TargetResolution) -> EntityRecord:
    if not resolution.ok or len(resolution.devices) != 1:
        raise ValueError("productivity_target_unresolved")
    device = resolution.devices[0]
    if len(device.entities) != 1:
        raise ValueError("productivity_target_invalid")
    entity = device.entities[0]
    if not entity.available:
        raise ValueError("productivity_target_unavailable")
    return entity


def resolve_productivity_target(
    intent: SemanticIntent,
    devices: tuple[DeviceRecord, ...],
    *,
    domain: str,
    default_entity_id: str = "",
) -> TargetResolution:
    resources = _resource_devices(devices, domain)
    if not resources:
        return TargetResolution(ok=False, reason=f"no_{domain}_resources")

    text = (intent.target_text or "").strip()
    if not text and default_entity_id:
        selected = tuple(
            resource
            for resource in resources
            if resource.entities[0].entity_id == default_entity_id
        )
        if len(selected) == 1:
            resource = selected[0]
            return TargetResolution(
                ok=True,
                devices=(resource,),
                confidence=1.0,
                reason="configured_default",
                resolution_kind="default",
                candidate_ids=(resource.bobi_id,),
            )
    if not text and len(resources) == 1:
        resource = resources[0]
        return TargetResolution(
            ok=True,
            devices=(resource,),
            confidence=1.0,
            reason="single_resource",
            resolution_kind="single",
            candidate_ids=(resource.bobi_id,),
        )
    if not text:
        return TargetResolution(
            ok=False,
            reason="productivity_target_required",
            ambiguous=len(resources) > 1,
            candidate_ids=tuple(resource.bobi_id for resource in resources[:5]),
        )
    return resolve_target(text, resources, domain_hint=domain)


def _read_allowed(policy: UserPolicy, *, domain: str, capability: str) -> str:
    if "*" not in policy.allowed_domains and domain not in policy.allowed_domains:
        return "domain_not_allowed"
    if "*" not in policy.allowed_capabilities and capability not in policy.allowed_capabilities:
        return "capability_not_allowed"
    if capability in policy.denied_capabilities:
        return "capability_denied"
    return ""


def _mutation_plan(
    *,
    request_id: str,
    entity: EntityRecord,
    domain: str,
    operation: str,
    data: dict[str, Any],
) -> ActionPlan:
    return ActionPlan(
        request_id=request_id,
        device_id=entity.entity_id,
        entity_id=entity.entity_id,
        domain=domain,
        action=operation,
        capability=f"{domain}.write",
        data=data,
        expected={},
        source="direct",
        confidence=1.0,
    )


def _provenance(intent: SemanticIntent, entity: EntityRecord) -> RequestProvenance:
    target = frozenset({entity.entity_id})
    return RequestProvenance(
        source_kind="direct",
        same_text=True,
        explicit_target_ids=target,
        negated=intent.negated,
        question=bool(intent.metadata.get("question", False)),
        literal_name=bool(intent.metadata.get("literal_name", False)),
        reference_only=intent.reference_only,
    )


async def process_productivity_intent(
    *,
    request_id: str,
    intent: SemanticIntent,
    devices: tuple[DeviceRecord, ...],
    policy: UserPolicy,
    calendar: CalendarAdapter,
    todo: TodoAdapter,
    default_calendar_entity_id: str = "",
    default_todo_entity_id: str = "",
) -> ProductivityResult:
    domain = intent.canonical_domain
    operation = intent.canonical_operation
    if domain not in {"calendar", "todo"}:
        return ProductivityResult("unsupported", "unsupported_productivity_domain", domain, operation)

    default_entity = (
        default_calendar_entity_id if domain == "calendar" else default_todo_entity_id
    )
    resolution = resolve_productivity_target(
        intent,
        devices,
        domain=domain,
        default_entity_id=default_entity,
    )
    if not resolution.ok:
        return ProductivityResult(
            "clarification",
            resolution.reason,
            domain,
            operation,
            resolution=resolution,
        )
    entity = _entity_from_resolution(resolution)
    metadata = intent.metadata if isinstance(intent.metadata, dict) else {}

    if operation in _READ_OPERATIONS:
        capability = f"{domain}.read"
        blocked = _read_allowed(policy, domain=domain, capability=capability)
        if blocked:
            return ProductivityResult(
                "blocked",
                blocked,
                domain,
                operation,
                entity_id=entity.entity_id,
                resolution=resolution,
            )
        if domain == "calendar":
            payload = await calendar.get_events(
                [entity.entity_id],
                start_date_time=str(metadata.get("start_date_time") or ""),
                end_date_time=str(metadata.get("end_date_time") or ""),
                duration=metadata.get("duration"),
            )
        else:
            payload = await todo.get_items(
                entity.entity_id,
                status=str(metadata.get("status") or "needs_action"),
            )
        return ProductivityResult(
            "completed",
            "read_completed",
            domain,
            operation,
            entity_id=entity.entity_id,
            resolution=resolution,
            payload=payload,
        )

    if intent.negated:
        return ProductivityResult(
            "blocked",
            "source_negated",
            domain,
            operation,
            entity_id=entity.entity_id,
            resolution=resolution,
        )

    data: dict[str, Any]
    adapter_operation: str
    if domain == "calendar" and operation in _CALENDAR_CREATE:
        adapter_operation = "create_event"
        data = {
            "summary": str(metadata.get("summary") or intent.value or ""),
            "start_date_time": str(metadata.get("start_date_time") or ""),
            "end_date_time": str(metadata.get("end_date_time") or ""),
            "start_date": str(metadata.get("start_date") or ""),
            "end_date": str(metadata.get("end_date") or ""),
            "in_offset": metadata.get("in_offset"),
            "description": str(metadata.get("description") or ""),
            "location": str(metadata.get("location") or ""),
        }
    elif domain == "todo" and operation in _TODO_ADD:
        adapter_operation = "add_item"
        data = {
            "item": str(metadata.get("item") or intent.value or ""),
            "due_date": str(metadata.get("due_date") or ""),
            "due_datetime": str(metadata.get("due_datetime") or ""),
            "description": str(metadata.get("description") or ""),
        }
    elif domain == "todo" and operation in _TODO_UPDATE:
        adapter_operation = "update_item"
        status = str(metadata.get("status") or "")
        if operation == "complete" and not status:
            status = "completed"
        elif operation == "uncomplete" and not status:
            status = "needs_action"
        data = {
            "item": str(metadata.get("item") or intent.value or ""),
            "rename": str(metadata.get("rename") or ""),
            "status": status,
            "due_date": str(metadata.get("due_date") or ""),
            "due_datetime": str(metadata.get("due_datetime") or ""),
            "description": metadata.get("description"),
        }
    elif domain == "todo" and operation in _TODO_REMOVE:
        adapter_operation = "remove_item"
        data = {"item": str(metadata.get("item") or intent.value or "")}
    elif domain == "todo" and operation in _TODO_CLEAR:
        adapter_operation = "remove_completed_items"
        data = {}
    else:
        return ProductivityResult(
            "unsupported",
            "unsupported_productivity_operation",
            domain,
            operation,
            entity_id=entity.entity_id,
            resolution=resolution,
        )

    plan = _mutation_plan(
        request_id=request_id,
        entity=entity,
        domain=domain,
        operation=adapter_operation,
        data=data,
    )
    decision = authorize_plan(
        plan,
        policy=policy,
        provenance=_provenance(intent, entity),
    )
    if not decision.allowed:
        return ProductivityResult(
            "approval_required" if decision.requires_approval else "blocked",
            decision.reason,
            domain,
            operation,
            entity_id=entity.entity_id,
            resolution=resolution,
            plans=(plan,),
        )

    if domain == "calendar":
        await calendar.create_event(entity.entity_id, **data)
    elif adapter_operation == "add_item":
        await todo.add_item(entity.entity_id, **data)
    elif adapter_operation == "update_item":
        await todo.update_item(entity.entity_id, **data)
    elif adapter_operation == "remove_item":
        await todo.remove_item(entity.entity_id, **data)
    else:
        await todo.remove_completed_items(entity.entity_id)

    return ProductivityResult(
        "completed",
        "mutation_completed",
        domain,
        operation,
        entity_id=entity.entity_id,
        resolution=resolution,
        plans=(plan,),
    )
