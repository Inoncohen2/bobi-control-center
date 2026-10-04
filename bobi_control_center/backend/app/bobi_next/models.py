"""Typed contracts for the generic Bobi engine.

The contracts deliberately contain no household-specific entity ids, aliases or
handlers.  Home Assistant is authoritative for live state; Bobi owns only
semantic identity, learned aliases/context and execution bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class EntityRecord:
    entity_id: str
    domain: str
    unique_id: str = ""
    platform: str = ""
    device_id: str = ""
    area_id: str = ""
    area_name: str = ""
    name: str = ""
    aliases: tuple[str, ...] = ()
    state: str = "unknown"
    attributes: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    capabilities: frozenset[str] = frozenset()
    limits: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeviceRecord:
    """One semantic device, possibly backed by several HA entities."""

    bobi_id: str
    stable_key: str
    ha_device_id: str = ""
    name: str = ""
    area_id: str = ""
    area_name: str = ""
    aliases: tuple[str, ...] = ()
    entities: tuple[EntityRecord, ...] = ()
    capabilities: frozenset[str] = frozenset()
    available: bool = True

    def primary_for(self, capability: str) -> EntityRecord | None:
        candidates = [e for e in self.entities if capability in e.capabilities]
        if not candidates:
            return None
        # Prefer an available entity, then a domain that naturally owns the
        # capability.  Ordering is deterministic so shadow tests are stable.
        return sorted(candidates, key=lambda e: (not e.available, e.entity_id))[0]


@dataclass(slots=True)
class TargetResolution:
    ok: bool
    devices: tuple[DeviceRecord, ...] = ()
    confidence: float = 0.0
    reason: str = "unresolved"
    resolution_kind: str = "unresolved"
    ambiguous: bool = False
    candidate_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class ActionPlan:
    """A side-effect-free plan.  Execution happens in a separate layer."""

    request_id: str
    device_id: str
    entity_id: str
    domain: str
    action: str
    capability: str
    data: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    source: Literal["direct", "context", "clarification", "instinct", "ai"] = "direct"
    confidence: float = 1.0
    requires_confirmation: bool = False
