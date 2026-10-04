"""End-to-end shadow planning for Bobi Next.

The shadow engine performs the same discovery -> resolution -> planning path that
production will use, but it never calls Home Assistant services.  It is the
bridge between the generic core and parity testing against the current Bobi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .ha_discovery import DiscoverySnapshot
from .memory import BobiMemory
from .models import ActionPlan, TargetResolution
from .planner import PlanError, build_plan
from .resolver import resolve_target


class DiscoveryClient(Protocol):
    async def snapshot(self) -> DiscoverySnapshot: ...


@dataclass(slots=True)
class ShadowRequest:
    request_id: str
    user_key: str
    text: str
    capability: str
    operation: str
    domain_hint: str = ""
    value: Any = None
    delta: float | None = None
    allow_group: bool = False


@dataclass(slots=True)
class ShadowResult:
    ok: bool
    reason: str
    request: ShadowRequest
    resolution: TargetResolution
    plans: tuple[ActionPlan, ...] = ()
    discovered_devices: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


async def run_shadow(
    request: ShadowRequest,
    *,
    discovery: DiscoveryClient,
    memory: BobiMemory,
) -> ShadowResult:
    """Resolve and plan a request without executing anything in Home Assistant."""

    snapshot = await discovery.snapshot()
    devices = snapshot.semantic_devices()
    memory.sync_devices(devices)

    active_context = memory.get_active_context(request.user_key) or {}
    active_device_id = str(active_context.get("bobi_device_id", ""))

    resolution = resolve_target(
        request.text,
        devices,
        domain_hint=request.domain_hint,
        capability=request.capability,
        active_device_id=active_device_id,
        learned_aliases=memory.aliases_for,
        allow_group=request.allow_group,
    )
    if not resolution.ok:
        return ShadowResult(
            ok=False,
            reason=resolution.reason,
            request=request,
            resolution=resolution,
            discovered_devices=len(devices),
        )

    source = "context" if resolution.resolution_kind == "context" else "direct"
    plans: list[ActionPlan] = []
    try:
        for device in resolution.devices:
            plans.append(
                build_plan(
                    request_id=request.request_id,
                    device=device,
                    capability=request.capability,
                    operation=request.operation,
                    value=request.value,
                    delta=request.delta,
                    source=source,
                    confidence=resolution.confidence,
                )
            )
    except (PlanError, TypeError, ValueError) as exc:
        return ShadowResult(
            ok=False,
            reason=str(exc),
            request=request,
            resolution=resolution,
            discovered_devices=len(devices),
        )

    if len(resolution.devices) == 1:
        device = resolution.devices[0]
        memory.set_active_context(
            request.user_key,
            bobi_device_id=device.bobi_id,
            area_id=device.area_id,
            object_type=request.domain_hint,
            payload={
                "entity_id": plans[0].entity_id,
                "capability": request.capability,
                "operation": request.operation,
            },
        )

    return ShadowResult(
        ok=True,
        reason="planned",
        request=request,
        resolution=resolution,
        plans=tuple(plans),
        discovered_devices=len(devices),
        metadata={
            "shadow": True,
            "executes_home_assistant": False,
            "resolution_kind": resolution.resolution_kind,
        },
    )
