"""Build Bobi's semantic device registry from Home Assistant data.

Inputs mirror HA's state/entity/device/area registries. The builder is pure and
side-effect free, which makes it suitable for shadow-mode parity tests.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .capabilities import infer_capabilities
from .models import DeviceRecord, EntityRecord


def _text(value: Any) -> str:
    return str(value or "").strip()


def _aliases(*values: Any) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        candidates = value if isinstance(value, (list, tuple, set)) else [value]
        for candidate in candidates:
            item = _text(candidate)
            if item and item.casefold() not in {x.casefold() for x in out}:
                out.append(item)
    return tuple(out)


def _bobi_id(stable_key: str) -> str:
    return "dev_" + hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:20]


def build_registry(
    states: Iterable[dict[str, Any]],
    entity_registry: Iterable[dict[str, Any]] = (),
    device_registry: Iterable[dict[str, Any]] = (),
    area_registry: Iterable[dict[str, Any]] = (),
) -> tuple[DeviceRecord, ...]:
    """Return semantic devices without mutating HA or Bobi storage.

    Stable identity preference is HA device_id, then integration
    (platform, unique_id), with entity_id only as a last-resort compatibility
    key for entities that HA itself cannot identify more stably.
    """

    er_by_id = {
        entity.get("entity_id"): entity
        for entity in entity_registry
        if entity.get("entity_id")
    }
    dr_by_id = {
        device.get("id"): device
        for device in device_registry
        if device.get("id")
    }
    ar_by_id = {
        area.get("area_id") or area.get("id"): area
        for area in area_registry
        if area.get("area_id") or area.get("id")
    }

    groups: dict[str, list[EntityRecord]] = defaultdict(list)
    meta: dict[str, dict[str, str]] = {}

    for state_row in states:
        entity_id = _text(state_row.get("entity_id"))
        if "." not in entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        raw_attributes = state_row.get("attributes")
        attributes = raw_attributes if isinstance(raw_attributes, dict) else {}
        er = er_by_id.get(entity_id, {})
        device_id = _text(er.get("device_id"))
        device = dr_by_id.get(device_id, {}) if device_id else {}
        entity_area_id = _text(er.get("area_id"))
        device_area_id = _text(device.get("area_id"))
        area_id = entity_area_id or device_area_id
        area = ar_by_id.get(area_id, {}) if area_id else {}
        area_name = _text(area.get("name"))
        unique_id = _text(er.get("unique_id"))
        platform = _text(er.get("platform"))

        stable_key = (
            f"ha-device:{device_id}"
            if device_id
            else f"entity-unique:{platform}:{unique_id}"
            if unique_id
            else f"entity-id:{entity_id}"
        )
        capabilities, limits = infer_capabilities(domain, attributes)
        name = (
            _text(er.get("name"))
            or _text(attributes.get("friendly_name"))
            or _text(er.get("original_name"))
            or entity_id
        )
        entity_aliases = _aliases(er.get("aliases", []), name, er.get("original_name"))
        available = _text(state_row.get("state")) not in {"unavailable", "unknown"}

        groups[stable_key].append(
            EntityRecord(
                entity_id=entity_id,
                domain=domain,
                unique_id=unique_id,
                platform=platform,
                device_id=device_id,
                area_id=area_id,
                area_name=area_name,
                name=name,
                aliases=entity_aliases,
                state=_text(state_row.get("state")) or "unknown",
                attributes=dict(attributes),
                available=available,
                capabilities=capabilities,
                limits=limits,
            )
        )
        if stable_key not in meta:
            device_name = (
                _text(device.get("name_by_user"))
                or _text(device.get("name"))
                or name
            )
            meta[stable_key] = {
                "device_id": device_id,
                "name": device_name,
                "area_id": area_id,
                "area_name": area_name,
            }

    devices: list[DeviceRecord] = []
    for stable_key, entities in groups.items():
        info = meta[stable_key]
        caps = frozenset(cap for entity in entities for cap in entity.capabilities)
        aliases = _aliases(
            info["name"],
            info["area_name"],
            *(entity.aliases for entity in entities),
        )
        devices.append(
            DeviceRecord(
                bobi_id=_bobi_id(stable_key),
                stable_key=stable_key,
                ha_device_id=info["device_id"],
                name=info["name"],
                area_id=info["area_id"],
                area_name=info["area_name"],
                aliases=aliases,
                entities=tuple(sorted(entities, key=lambda e: e.entity_id)),
                capabilities=caps,
                available=any(e.available for e in entities),
            )
        )

    return tuple(
        sorted(
            devices,
            key=lambda d: (d.area_name.casefold(), d.name.casefold(), d.bobi_id),
        )
    )
