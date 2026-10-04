"""Capability-driven, side-effect-free action planning.

The planner translates a resolved semantic device into native HA service data.
It never sends the service call. Validation and read-after-write expectations
are part of the plan so execution can remain fail-closed and verifiable.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .models import ActionPlan, DeviceRecord


class PlanError(ValueError):
    pass


def _quantize(value: float, minimum: float, step: float) -> float:
    if step <= 0:
        return float(value)
    units = (Decimal(str(value)) - Decimal(str(minimum))) / Decimal(str(step))
    units = units.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(Decimal(str(minimum)) + units * Decimal(str(step)))


def _entity(device: DeviceRecord, capability: str):
    entity = device.primary_for(capability)
    if not entity:
        raise PlanError(f"capability_not_supported:{capability}")
    if not entity.available:
        raise PlanError("target_unavailable")
    return entity


def _choice(entity, *, limits_key: str, value: Any, error: str) -> str:
    choice = str(value or "").strip()
    options = entity.limits.get(limits_key, [])
    if not choice or not isinstance(options, (list, tuple, set)) or choice not in options:
        raise PlanError(error)
    return choice


def build_plan(
    *,
    request_id: str,
    device: DeviceRecord,
    capability: str,
    operation: str,
    value: Any = None,
    delta: float | None = None,
    source: str = "direct",
    confidence: float = 1.0,
) -> ActionPlan:
    entity = _entity(device, capability)
    domain = entity.domain
    data: dict[str, Any] = {"entity_id": entity.entity_id}
    expected: dict[str, Any] = {}

    if capability == "power":
        if operation not in {"on", "off"}:
            raise PlanError("invalid_power_operation")
        action = "turn_on" if operation == "on" else "turn_off"
        if domain == "media_player" and operation == "on":
            expected["state_not"] = ["off", "unavailable", "unknown"]
        else:
            expected["state"] = operation

    elif capability == "temperature" and domain == "climate":
        current = entity.attributes.get("temperature")
        if value is None and delta is None:
            raise PlanError("temperature_value_missing")
        if value is None:
            if current is None:
                raise PlanError("current_target_temperature_unknown")
            target = float(current) + float(delta or 0)
        else:
            target = float(value)
        minimum = float(
            entity.limits.get("min_temp", entity.attributes.get("min_temp", 7))
        )
        maximum = float(
            entity.limits.get("max_temp", entity.attributes.get("max_temp", 35))
        )
        step = float(
            entity.limits.get(
                "temp_step",
                entity.attributes.get("target_temp_step", 0.5),
            )
            or 0.5
        )
        target = _quantize(target, minimum, step)
        if target < minimum or target > maximum:
            raise PlanError("temperature_out_of_range")
        action = "set_temperature"
        data["temperature"] = target
        expected["attribute"] = "temperature"
        expected["value"] = target
        expected["tolerance"] = max(0.01, step / 2)

    elif capability in {"hvac_mode", "fan_mode", "swing_mode", "preset_mode"}:
        if domain != "climate":
            raise PlanError(f"unsupported_plan:{domain}:{capability}")
        mapping = {
            "hvac_mode": ("set_hvac_mode", "hvac_mode", "hvac_modes"),
            "fan_mode": ("set_fan_mode", "fan_mode", "fan_modes"),
            "swing_mode": ("set_swing_mode", "swing_mode", "swing_modes"),
            "preset_mode": ("set_preset_mode", "preset_mode", "preset_modes"),
        }
        action, data_key, limits_key = mapping[capability]
        selected = _choice(
            entity,
            limits_key=limits_key,
            value=value,
            error=f"{capability}_not_supported",
        )
        data[data_key] = selected
        if capability == "hvac_mode":
            expected["state"] = selected
        else:
            expected.update({"attribute": data_key, "value": selected})

    elif capability == "brightness" and domain == "light":
        if value is None and delta is None:
            raise PlanError("brightness_value_missing")
        if value is None:
            current_raw = entity.attributes.get("brightness")
            if current_raw is None:
                raise PlanError("current_brightness_unknown")
            current_pct = float(current_raw) / 255.0 * 100.0
            target = current_pct + float(delta or 0)
        else:
            target = float(value)
        target = max(0.0, min(100.0, target))
        action = "turn_on" if target > 0 else "turn_off"
        if target > 0:
            data["brightness_pct"] = round(target)
            expected.update(
                {
                    "attribute": "brightness_pct",
                    "value": round(target),
                    "tolerance": 2,
                }
            )
        else:
            expected["state"] = "off"

    elif capability == "position" and domain == "cover":
        if value is None:
            raise PlanError("position_value_missing")
        target = float(value)
        if not 0 <= target <= 100:
            raise PlanError("position_out_of_range")
        action = "set_cover_position"
        data["position"] = round(target)
        expected.update(
            {
                "attribute": "current_position",
                "value": round(target),
                "tolerance": 2,
            }
        )

    elif capability == "tilt_position" and domain == "cover":
        if value is None:
            raise PlanError("tilt_position_value_missing")
        target = float(value)
        if not 0 <= target <= 100:
            raise PlanError("tilt_position_out_of_range")
        action = "set_cover_tilt_position"
        data["tilt_position"] = round(target)
        expected.update(
            {
                "attribute": "current_tilt_position",
                "value": round(target),
                "tolerance": 2,
            }
        )

    elif capability in {"open", "close", "stop"} and domain == "cover":
        action = {
            "open": "open_cover",
            "close": "close_cover",
            "stop": "stop_cover",
        }[capability]
        if capability in {"open", "close"}:
            expected["state"] = "open" if capability == "open" else "closed"

    elif capability == "percentage" and domain == "fan":
        if value is None and delta is None:
            raise PlanError("fan_percentage_value_missing")
        current = entity.attributes.get("percentage")
        if value is None:
            if current is None:
                raise PlanError("current_fan_percentage_unknown")
            target = float(current) + float(delta or 0)
        else:
            target = float(value)
        target = max(0.0, min(100.0, target))
        action = "set_percentage"
        data["percentage"] = round(target)
        expected.update(
            {"attribute": "percentage", "value": round(target), "tolerance": 1}
        )

    elif capability == "preset_mode" and domain == "fan":
        selected = _choice(
            entity,
            limits_key="preset_modes",
            value=value,
            error="preset_mode_not_supported",
        )
        action = "set_preset_mode"
        data["preset_mode"] = selected
        expected.update({"attribute": "preset_mode", "value": selected})

    elif capability in {"start", "stop", "return_home"} and domain == "vacuum":
        action = {
            "start": "start",
            "stop": "stop",
            "return_home": "return_to_base",
        }[capability]
        if capability == "start":
            expected["state_any"] = ["cleaning"]
        elif capability == "return_home":
            expected["state_any"] = ["returning", "docked"]

    elif capability == "fan_speed" and domain == "vacuum":
        selected = _choice(
            entity,
            limits_key="fan_speeds",
            value=value,
            error="fan_speed_not_supported",
        )
        action = "set_fan_speed"
        data["fan_speed"] = selected
        expected.update({"attribute": "fan_speed", "value": selected})

    elif capability == "lock" and domain == "lock":
        action = "lock"
        expected["state"] = "locked"
    elif capability == "unlock" and domain == "lock":
        action = "unlock"
        expected["state"] = "unlocked"
    elif capability == "press" and domain == "button":
        action = "press"
    elif capability == "set_value" and domain == "number":
        if value is None:
            raise PlanError("number_value_missing")
        target = float(value)
        minimum = float(entity.limits.get("min", target))
        maximum = float(entity.limits.get("max", target))
        step = float(entity.limits.get("step", 0) or 0)
        if target < minimum or target > maximum:
            raise PlanError("number_out_of_range")
        target = _quantize(target, minimum, step) if step > 0 else target
        action = "set_value"
        data["value"] = target
        expected.update(
            {"state": str(target)}
        )
    elif capability == "select_option" and domain == "select":
        options = entity.limits.get("options", [])
        if value not in options:
            raise PlanError("option_not_supported")
        action = "select_option"
        data["option"] = value
        expected.update({"state": value})
    elif capability in {"play", "pause", "stop"} and domain == "media_player":
        action = {
            "play": "media_play",
            "pause": "media_pause",
            "stop": "media_stop",
        }[capability]
        expected["state_any"] = {
            "play": ["playing"],
            "pause": ["paused"],
            "stop": ["idle", "off", "paused"],
        }[capability]
    elif capability == "volume" and domain == "media_player":
        if value is None:
            raise PlanError("volume_value_missing")
        target = float(value)
        if target > 1:
            target /= 100.0
        if not 0 <= target <= 1:
            raise PlanError("volume_out_of_range")
        action = "volume_set"
        data["volume_level"] = target
        expected.update(
            {"attribute": "volume_level", "value": target, "tolerance": 0.02}
        )
    else:
        raise PlanError(f"unsupported_plan:{domain}:{capability}")

    return ActionPlan(
        request_id=request_id,
        device_id=device.bobi_id,
        entity_id=entity.entity_id,
        domain=domain,
        action=action,
        capability=capability,
        data=data,
        expected=expected,
        source=source,  # type: ignore[arg-type]
        confidence=float(confidence),
    )
