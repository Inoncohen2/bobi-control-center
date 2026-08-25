"""Turn raw entities into friendly Bobi devices.

This is the translation layer that lets the frontend stay free of Home Assistant
vocabulary. Everything HA-shaped stops here.
"""

from __future__ import annotations

from app.models import Advanced, Device, DeviceCategory, RawEntity

#: HA domain (and device_class) → Bobi category.
_DOMAIN_CATEGORY: dict[str, DeviceCategory] = {
    "light": DeviceCategory.LIGHT,
    "climate": DeviceCategory.CLIMATE,
    "camera": DeviceCategory.CAMERA,
    "cover": DeviceCategory.COVER,
    "switch": DeviceCategory.SWITCH,
    "vacuum": DeviceCategory.VACUUM,
    "sensor": DeviceCategory.SENSOR,
    "binary_sensor": DeviceCategory.SENSOR,
    "media_player": DeviceCategory.SWITCH,
}

_CATEGORY_ICON: dict[DeviceCategory, str] = {
    DeviceCategory.LIGHT: "lightbulb",
    DeviceCategory.CLIMATE: "air-vent",
    DeviceCategory.CAMERA: "camera",
    DeviceCategory.COVER: "blinds",
    DeviceCategory.SWITCH: "toggle-right",
    DeviceCategory.BOILER: "water",
    DeviceCategory.VACUUM: "bot",
    DeviceCategory.SENSOR: "gauge",
}

_CATEGORY_CAPABILITIES: dict[DeviceCategory, list[str]] = {
    DeviceCategory.LIGHT: ["turn_on", "turn_off", "set_brightness"],
    DeviceCategory.CLIMATE: ["turn_on", "turn_off", "set_temperature"],
    DeviceCategory.CAMERA: ["snapshot"],
    DeviceCategory.COVER: ["open", "close", "set_position"],
    DeviceCategory.SWITCH: ["turn_on", "turn_off"],
    DeviceCategory.BOILER: ["turn_on", "turn_off", "run_for"],
    DeviceCategory.VACUUM: ["start", "stop", "return_to_base"],
    DeviceCategory.SENSOR: ["read"],
}

#: Bobi-level state → Hebrew label, per category where it matters.
_STATE_LABELS: dict[str, str] = {
    "on": "דולק",
    "off": "כבוי",
    "open": "פתוח",
    "closed": "סגור",
    "cool": "מקרר",
    "heat": "מחמם",
    "fan_only": "מאוורר",
    "docked": "בעמדת טעינה",
    "cleaning": "מנקה",
    "recording": "מקליט",
    "idle": "ממתין",
    "unavailable": "לא זמין",
    "unknown": "לא ידוע",
}

#: Explicit id overrides so the ids in fixtures, automations and the Shabbat
#: config all line up with the ids derived here.
_ID_OVERRIDES: dict[str, str] = {
    "light.demo_living_room_main": "living_room_light",
    "light.demo_living_room_strip": "living_room_strip",
    "climate.demo_living_room_ac": "living_room_ac",
    "cover.demo_living_room_blind": "living_room_blind",
    "media_player.demo_living_room_tv": "living_room_tv",
    "sensor.demo_living_room_temperature": "living_room_temperature",
    "light.demo_kitchen_main": "kitchen_light",
    "switch.demo_kitchen_kettle": "kettle",
    "switch.demo_boiler": "boiler",
    "vacuum.demo_robot": "robot_vacuum",
    "light.demo_parents_main": "parents_light",
    "climate.demo_parents_ac": "parents_ac",
    "cover.demo_parents_blind": "parents_blind",
    "light.demo_girls_main": "girls_light",
    "climate.demo_girls_ac": "girls_ac",
    "camera.demo_lia_room": "lia_camera",
    "camera.demo_shaya_room": "shaya_camera",
    "light.demo_garden": "garden_light",
    "switch.demo_irrigation": "irrigation",
    "camera.demo_entrance": "entrance_camera",
    "binary_sensor.demo_front_door": "front_door",
    "sensor.demo_outdoor_temperature": "outdoor_temperature",
}


def _device_id(entity: RawEntity) -> str:
    if entity.entity_id in _ID_OVERRIDES:
        return _ID_OVERRIDES[entity.entity_id]
    # Fall back to the object id with the vendor "demo_" prefix stripped.
    object_id = entity.entity_id.split(".", 1)[-1]
    return object_id.removeprefix("demo_")


def _category(entity: RawEntity) -> DeviceCategory:
    domain = entity.entity_id.split(".", 1)[0]
    # The boiler is a switch in HA but its own thing to a household.
    if "boiler" in entity.entity_id or entity.friendly_name.strip() == "דוד":
        return DeviceCategory.BOILER
    return _DOMAIN_CATEGORY.get(domain, DeviceCategory.SWITCH)


def _state_label(state: str, available: bool) -> str:
    if not available:
        return _STATE_LABELS["unavailable"]
    if state.replace(".", "", 1).isdigit():
        return state
    return _STATE_LABELS.get(state, state)


def _capabilities(category: DeviceCategory, entity: RawEntity) -> list[str]:
    caps = list(_CATEGORY_CAPABILITIES.get(category, ["turn_on", "turn_off"]))
    if category is DeviceCategory.CLIMATE and "hvac_modes" in entity.attributes:
        caps.append("set_mode")
    return caps


def to_device(entity: RawEntity) -> Device:
    """Map one raw entity onto the Bobi device model."""
    category = _category(entity)
    unit = entity.attributes.get("unit_of_measurement")
    state = entity.state if entity.available else "unavailable"
    label = _state_label(state, entity.available)
    if unit and entity.available:
        label = f"{state}{unit}"

    return Device(
        id=_device_id(entity),
        display_name=entity.friendly_name,
        room=entity.area or "ללא חדר",
        category=category,
        state=state,
        state_label=label,
        available=entity.available,
        aliases=entity.aliases or [entity.friendly_name],
        capabilities=_capabilities(category, entity),
        icon=_CATEGORY_ICON.get(category, "plug"),
        advanced=Advanced(
            entity_id=entity.entity_id,
            object_id=entity.entity_id.split(".", 1)[-1],
            integration=entity.integration,
            raw=dict(entity.attributes),
        ),
    )


def to_devices(entities: list[RawEntity]) -> list[Device]:
    return [to_device(entity) for entity in entities]
