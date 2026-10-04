"""Generic Home Assistant capability inference.

No entity id, room name or vendor is special-cased here.  Capabilities are
inferred from HA domains plus live attributes exposed by the integration.
"""

from __future__ import annotations

from typing import Any


def _seq(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) else []


def infer_capabilities(domain: str, attributes: dict[str, Any]) -> tuple[frozenset[str], dict[str, Any]]:
    domain = domain.lower().strip()
    caps: set[str] = set()
    limits: dict[str, Any] = {}

    if domain in {"light", "switch", "input_boolean"}:
        caps.add("power")
    if domain == "light":
        color_modes = {str(v) for v in _seq(attributes.get("supported_color_modes"))}
        if attributes.get("brightness") is not None or color_modes - {"onoff"}:
            caps.add("brightness")
            limits.update({"min_brightness_pct": 0, "max_brightness_pct": 100})
        if (
            attributes.get("color_temp_kelvin") is not None
            or attributes.get("min_color_temp_kelvin") is not None
            or any(v in color_modes for v in {"color_temp", "white"})
        ):
            caps.add("color_temp")
            if attributes.get("min_color_temp_kelvin") is not None:
                limits["min_kelvin"] = attributes["min_color_temp_kelvin"]
            if attributes.get("max_color_temp_kelvin") is not None:
                limits["max_kelvin"] = attributes["max_color_temp_kelvin"]
        if any(v in color_modes for v in {"hs", "xy", "rgb", "rgbw", "rgbww"}):
            caps.add("color")

    elif domain == "climate":
        caps.update({"power", "hvac_mode"})
        if attributes.get("temperature") is not None or attributes.get("min_temp") is not None:
            caps.add("temperature")
            for source, target in (
                ("min_temp", "min_temp"),
                ("max_temp", "max_temp"),
                ("target_temp_step", "temp_step"),
            ):
                if attributes.get(source) is not None:
                    limits[target] = attributes[source]
        if _seq(attributes.get("fan_modes")):
            caps.add("fan_mode")
            limits["fan_modes"] = _seq(attributes.get("fan_modes"))
        if _seq(attributes.get("swing_modes")):
            caps.add("swing_mode")
            limits["swing_modes"] = _seq(attributes.get("swing_modes"))
        if _seq(attributes.get("preset_modes")):
            caps.add("preset_mode")
            limits["preset_modes"] = _seq(attributes.get("preset_modes"))
        hvac_modes = _seq(attributes.get("hvac_modes"))
        if hvac_modes:
            limits["hvac_modes"] = hvac_modes

    elif domain == "cover":
        caps.update({"open", "close", "stop"})
        if attributes.get("current_position") is not None:
            caps.add("position")
            limits.update({"min_position": 0, "max_position": 100})
        if attributes.get("current_tilt_position") is not None:
            caps.add("tilt_position")

    elif domain == "fan":
        caps.add("power")
        if attributes.get("percentage") is not None or _seq(attributes.get("percentage_step")):
            caps.add("percentage")
            limits.update({"min_percentage": 0, "max_percentage": 100})
        if _seq(attributes.get("preset_modes")):
            caps.add("preset_mode")
            limits["preset_modes"] = _seq(attributes.get("preset_modes"))

    elif domain == "vacuum":
        caps.update({"start", "stop", "return_home", "status"})
        if _seq(attributes.get("fan_speed_list")) or attributes.get("fan_speed") is not None:
            caps.add("fan_speed")
            limits["fan_speeds"] = _seq(attributes.get("fan_speed_list"))
        if attributes.get("battery_level") is not None:
            caps.add("battery")

    elif domain == "lock":
        caps.update({"lock", "unlock", "status"})
    elif domain == "button":
        caps.add("press")
    elif domain == "number":
        caps.add("set_value")
        for source, target in (("min", "min"), ("max", "max"), ("step", "step")):
            if attributes.get(source) is not None:
                limits[target] = attributes[source]
    elif domain == "select":
        caps.add("select_option")
        limits["options"] = _seq(attributes.get("options"))
    elif domain == "media_player":
        caps.update({"power", "play", "pause", "stop", "volume"})
        limits.update({"min_volume": 0.0, "max_volume": 1.0})
    elif domain == "camera":
        caps.update({"snapshot", "stream", "status"})
    elif domain in {"sensor", "binary_sensor"}:
        caps.add("read")

    return frozenset(caps), limits
