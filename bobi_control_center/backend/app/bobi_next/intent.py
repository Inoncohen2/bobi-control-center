"""Canonical semantic intent contract for Bobi Next.

Language understanding is deliberately separated from target resolution and
execution.  An AI/parser may produce an intent, but deterministic code remains
responsible for binding it to discovered HA devices and validating the action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_DOMAIN_ALIASES = {
    "lighting": "light",
    "lights": "light",
    "switches": "switch",
    "cameras": "camera",
    "vacuum": "vacuum",
    "climate": "climate",
    "cover": "cover",
    "covers": "cover",
    "media": "media_player",
}

_OPERATION_ALIASES = {
    "turn_on": "on",
    "turn_off": "off",
    "open_cover": "open",
    "close_cover": "close",
    "set_cover_position": "set_position",
    "return": "return_home",
    "return_to_base": "return_home",
}


def canonical_domain(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    return _DOMAIN_ALIASES.get(normalized, normalized)


def canonical_operation(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    return _OPERATION_ALIASES.get(normalized, normalized)


@dataclass(slots=True)
class SemanticIntent:
    raw_text: str
    family: str
    domain: str
    operation: str
    target_text: str = ""
    target_scopes: tuple[str, ...] = ()
    aggregate_scope: str = ""
    value_kind: str = "none"
    value: Any = None
    delta: float | None = None
    scheduled: bool = False
    conditional: bool = False
    contextual: bool = False
    reference_only: bool = False
    multi_target: bool = False
    exclusion: bool = False
    negated: bool = False
    confidence: float = 0.0
    schedule_kind: str = ""
    schedule_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_domain(self) -> str:
        return canonical_domain(self.domain)

    @property
    def canonical_operation(self) -> str:
        return canonical_operation(self.operation)

    @property
    def mutating(self) -> bool:
        return self.canonical_operation not in {"", "get", "read", "status", "query"}
