"""Deterministic routing from semantic intent to a Bobi capability contract.

The language layer says *what the user means*. This router says which generic
capability must satisfy that meaning. It contains no entity ids, room names or
vendor-specific device knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .intent import SemanticIntent


class RoutingError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class RoutedIntent:
    domain_hint: str
    capability: str
    operation: str
    value: Any = None
    delta: float | None = None
    allow_group: bool = False
    defer_execution: bool = False
    defer_reason: str = ""


def _defer(intent: SemanticIntent) -> tuple[bool, str]:
    if intent.scheduled:
        return True, "scheduled"
    if intent.conditional:
        return True, "conditional"
    return False, ""


def route_intent(intent: SemanticIntent) -> RoutedIntent:
    domain = intent.canonical_domain
    operation = intent.canonical_operation
    kind = str(intent.value_kind or "").casefold()
    defer, defer_reason = _defer(intent)

    if domain in {"light", "switch", "input_boolean"} and operation in {"on", "off"}:
        return RoutedIntent(
            domain,
            "power",
            operation,
            allow_group=intent.multi_target,
            defer_execution=defer,
            defer_reason=defer_reason,
        )

    if domain == "light" and kind in {"brightness", "percentage"}:
        return RoutedIntent(
            domain,
            "brightness",
            "set",
            value=intent.value,
            delta=intent.delta,
            allow_group=intent.multi_target,
            defer_execution=defer,
            defer_reason=defer_reason,
        )

    if domain == "climate":
        if kind in {"temperature", "degrees", "delta_temperature"} or intent.delta is not None:
            return RoutedIntent(
                domain,
                "temperature",
                "set",
                value=intent.value,
                delta=intent.delta,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if operation in {"on", "off"}:
            return RoutedIntent(
                domain,
                "power",
                operation,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if kind == "hvac_mode":
            return RoutedIntent(domain, "hvac_mode", "set", value=intent.value)
        if kind == "fan_mode":
            return RoutedIntent(domain, "fan_mode", "set", value=intent.value)
        if kind == "swing_mode":
            return RoutedIntent(domain, "swing_mode", "set", value=intent.value)
        if kind == "preset_mode":
            return RoutedIntent(domain, "preset_mode", "set", value=intent.value)

    if domain == "cover":
        if operation in {"open", "close", "stop"} and intent.value is None:
            return RoutedIntent(
                domain,
                operation,
                operation,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if operation == "set_position" or kind in {"position", "percentage"}:
            return RoutedIntent(
                domain,
                "position",
                "set",
                value=intent.value,
                delta=intent.delta,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if kind in {"tilt", "tilt_position"}:
            return RoutedIntent(
                domain,
                "tilt_position",
                "set",
                value=intent.value,
                delta=intent.delta,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )

    if domain == "fan":
        if operation in {"on", "off"}:
            return RoutedIntent(
                domain,
                "power",
                operation,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if kind in {"percentage", "speed", "fan_percentage"}:
            return RoutedIntent(
                domain,
                "percentage",
                "set",
                value=intent.value,
                delta=intent.delta,
                allow_group=intent.multi_target,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if kind == "preset_mode":
            return RoutedIntent(domain, "preset_mode", "set", value=intent.value)

    if domain == "vacuum":
        if operation in {"start", "stop", "return_home"}:
            return RoutedIntent(
                domain,
                operation,
                operation,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if kind in {"fan_speed", "speed"}:
            return RoutedIntent(
                domain,
                "fan_speed",
                "set",
                value=intent.value,
                defer_execution=defer,
                defer_reason=defer_reason,
            )

    if domain == "media_player":
        if operation in {"on", "off"}:
            return RoutedIntent(
                domain,
                "power",
                operation,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if operation in {"play", "pause", "stop"}:
            return RoutedIntent(
                domain,
                operation,
                operation,
                defer_execution=defer,
                defer_reason=defer_reason,
            )
        if operation in {"volume", "set_volume"} or kind in {"volume", "percentage"}:
            return RoutedIntent(
                domain,
                "volume",
                "set",
                value=intent.value,
                delta=intent.delta,
                defer_execution=defer,
                defer_reason=defer_reason,
            )

    if domain == "lock" and operation in {"lock", "unlock"}:
        return RoutedIntent(
            domain,
            operation,
            operation,
            defer_execution=defer,
            defer_reason=defer_reason,
        )

    if domain == "button" and operation in {"press", "on"}:
        return RoutedIntent(domain, "press", "press")

    if domain == "number" and operation in {"set", "set_value"}:
        return RoutedIntent(
            domain,
            "set_value",
            "set",
            value=intent.value,
            defer_execution=defer,
            defer_reason=defer_reason,
        )

    if domain == "select" and operation in {"set", "select_option"}:
        return RoutedIntent(
            domain,
            "select_option",
            "set",
            value=intent.value,
            defer_execution=defer,
            defer_reason=defer_reason,
        )

    raise RoutingError(f"unsupported_intent:{domain}:{operation}:{kind}")
