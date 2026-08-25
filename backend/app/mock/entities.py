"""Mock raw entities.

This module is the *only* fixture file that speaks Home Assistant vocabulary,
mirroring what a real adapter would receive from the HA state machine. The
service layer turns these into friendly Bobi devices.

All identifiers are invented. Nothing here corresponds to a real installation.
"""

from __future__ import annotations

from app.models import RawEntity

# Rooms used across every fixture in this package.
ROOMS = ["סלון", "מטבח", "חדר הורים", "חדר בנות", "חוץ"]


def _e(
    entity_id: str,
    friendly_name: str,
    state: str,
    area: str,
    *,
    available: bool = True,
    integration: str = "demo",
    aliases: list[str] | None = None,
    **attributes: object,
) -> RawEntity:
    return RawEntity(
        entity_id=entity_id,
        friendly_name=friendly_name,
        state=state,
        area=area,
        available=available,
        integration=integration,
        aliases=aliases or [],
        attributes=attributes,
    )


MOCK_ENTITIES: list[RawEntity] = [
    # --- סלון -------------------------------------------------------------
    _e(
        "light.demo_living_room_main",
        "אור סלון",
        "on",
        "סלון",
        aliases=["אור סלון", "האור בסלון", "תאורת הסלון"],
        brightness=180,
        supported_color_modes=["brightness"],
    ),
    _e(
        "light.demo_living_room_strip",
        "תאורת אווירה סלון",
        "off",
        "סלון",
        aliases=["תאורת אווירה", "לדים בסלון"],
        supported_color_modes=["hs"],
    ),
    _e(
        "climate.demo_living_room_ac",
        "מזגן סלון",
        "off",
        "סלון",
        aliases=["מזגן סלון", "המזגן בסלון", "מזגן הסלון"],
        temperature=24,
        current_temperature=27,
        hvac_modes=["off", "cool", "heat", "fan_only"],
    ),
    _e(
        "cover.demo_living_room_blind",
        "תריס סלון",
        "open",
        "סלון",
        aliases=["תריס סלון", "התריס בסלון"],
        current_position=100,
    ),
    _e(
        "media_player.demo_living_room_tv",
        "טלוויזיה סלון",
        "off",
        "סלון",
        integration="cast",
        aliases=["טלוויזיה", "הטלוויזיה בסלון"],
    ),
    _e(
        "sensor.demo_living_room_temperature",
        "טמפרטורה סלון",
        "27.4",
        "סלון",
        aliases=["טמפרטורה בסלון"],
        unit_of_measurement="°C",
        device_class="temperature",
    ),
    # --- מטבח -------------------------------------------------------------
    _e(
        "light.demo_kitchen_main",
        "אור מטבח",
        "off",
        "מטבח",
        aliases=["אור מטבח", "האור במטבח", "תאורת המטבח"],
        brightness=0,
        supported_color_modes=["brightness"],
    ),
    _e(
        "switch.demo_kitchen_kettle",
        "קומקום",
        "off",
        "מטבח",
        aliases=["קומקום", "הקומקום"],
    ),
    _e(
        "switch.demo_boiler",
        "דוד",
        "off",
        "מטבח",
        aliases=["דוד", "דוד שמש", "המים החמים"],
        icon="mdi:water-boiler",
    ),
    _e(
        "vacuum.demo_robot",
        "רובי",
        "docked",
        "מטבח",
        integration="roborock",
        aliases=["רובי", "השואב", "הרובוט"],
        battery_level=92,
        fan_speed="balanced",
    ),
    # --- חדר הורים --------------------------------------------------------
    _e(
        "light.demo_parents_main",
        "אור חדר הורים",
        "off",
        "חדר הורים",
        aliases=["אור חדר הורים", "האור בחדר הורים"],
    ),
    _e(
        "climate.demo_parents_ac",
        "מזגן הורים",
        "off",
        "חדר הורים",
        aliases=["מזגן הורים", "מזגן חדר הורים", "המזגן בחדר הורים"],
        temperature=23,
        current_temperature=25,
        hvac_modes=["off", "cool", "heat"],
    ),
    _e(
        "cover.demo_parents_blind",
        "תריס חדר הורים",
        "closed",
        "חדר הורים",
        aliases=["תריס הורים"],
        current_position=0,
    ),
    # --- חדר בנות ---------------------------------------------------------
    _e(
        "light.demo_girls_main",
        "אור חדר בנות",
        "on",
        "חדר בנות",
        aliases=["אור חדר בנות", "האור אצל הבנות"],
    ),
    _e(
        "climate.demo_girls_ac",
        "מזגן חדר בנות",
        "cool",
        "חדר בנות",
        aliases=["מזגן בנות", "המזגן בחדר בנות"],
        temperature=24,
        current_temperature=24,
        hvac_modes=["off", "cool", "heat"],
    ),
    _e(
        "camera.demo_lia_room",
        "מצלמת ליה",
        "unavailable",
        "חדר בנות",
        available=False,
        integration="generic",
        aliases=["מצלמת ליה", "המצלמה של ליה"],
    ),
    _e(
        "camera.demo_shaya_room",
        "מצלמת שיה",
        "unavailable",
        "חדר בנות",
        available=False,
        integration="generic",
        aliases=["מצלמת שיה", "המצלמה של שיה"],
    ),
    # --- חוץ --------------------------------------------------------------
    _e(
        "light.demo_garden",
        "אור חצר",
        "off",
        "חוץ",
        aliases=["אור חצר", "התאורה בחצר", "אור בחוץ"],
    ),
    _e(
        "switch.demo_irrigation",
        "השקיה",
        "off",
        "חוץ",
        aliases=["השקיה", "המים בגינה"],
    ),
    _e(
        "camera.demo_entrance",
        "מצלמת כניסה",
        "recording",
        "חוץ",
        integration="generic",
        aliases=["מצלמת כניסה", "המצלמה בכניסה"],
    ),
    _e(
        "binary_sensor.demo_front_door",
        "דלת כניסה",
        "off",
        "חוץ",
        aliases=["דלת כניסה", "הדלת"],
        device_class="door",
    ),
    _e(
        "sensor.demo_outdoor_temperature",
        "טמפרטורה בחוץ",
        "31.2",
        "חוץ",
        aliases=["טמפרטורה בחוץ", "מזג האוויר"],
        unit_of_measurement="°C",
        device_class="temperature",
    ),
]
