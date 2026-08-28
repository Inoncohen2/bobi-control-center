"""Fresh device states, read from Home Assistant instead of rendered by a script.

## Why this exists

Every read of the devices family used to render a Jinja template inside Home
Assistant: `bobi_cc_devices` walks the house, formats thirty-odd items and
hands back JSON it assembled by hand. That is the slowest part of a refresh,
and on the evidence of this release it is also the most fragile — one family
answered 500 to every call because a `datetime` cannot be serialised out of a
template, and two more arrived in the wrong shape for want of any schema.

So the two halves are split by how often they change:

* the **catalogue** — which devices exist, their canonical ids, their Hebrew
  names, their capabilities and limits — still comes from the bridge, and is
  cached, because it changes when the household changes a device and not
  otherwise. Keeping it there is deliberate: it is configuration the household
  edits in Home Assistant, and moving it into this application would mean a new
  add-on release every time a lamp is renamed.
* the **live state** — what is on right now — comes straight from
  `/api/states`, which has no template and no shape to get wrong.

## What this is not

It is not a way to see the whole house. `/api/states` returns every entity in
Home Assistant, and `overlay` keeps only entities the bridge's own catalogue
already named. An entity the bridge did not publish is not merely hidden from
the client — it never gets a canonical id, so there is nothing to attach it to.

## The cost, stated plainly

Deciding whether a raw state means "on" needs the same domain knowledge the
bridge already has, so `ON_STATES` below duplicates it. That is a real cost and
it is bounded on purpose: it covers the switch position only. Numbers, choices
and everything else keep the value the bridge computed, because working those
out would mean copying the whole capability model into this application — which
is the thing the contract-driven design exists to avoid.

Everything here fails soft. No mapping, no states, an unfamiliar domain, an
unfamiliar state: the bridge's own value stands, which is exactly the behaviour
that existed before this module did.
"""

from __future__ import annotations

from typing import Any

from app.models.manage import ResourceSnapshot
from app.services import normalize
from app.services.resources import humanise

#: Raw states that mean "this is on", per Home Assistant domain.
#:
#: Duplicated from the bridge on purpose — see the module docstring. A domain
#: absent from this table is never overlaid, so adding a device class this
#: application has not thought about cannot produce a wrong switch position; it
#: produces the bridge's answer, which is the one it produced before.
#:
#: `vacuum` is why this is a table rather than `state != "off"`: a docked vacuum
#: is idle, not running, and `!= "off"` would have drawn its switch as on.
ON_STATES: dict[str, frozenset[str]] = {
    "light": frozenset({"on"}),
    "switch": frozenset({"on"}),
    "input_boolean": frozenset({"on"}),
    "fan": frozenset({"on"}),
    "media_player": frozenset({"on", "playing", "paused", "idle"}),
    # A climate entity's state *is* its mode, and every mode but "off" is on.
    "climate": frozenset({"auto", "cool", "dry", "heat", "fan_only", "heat_cool", "on"}),
    "vacuum": frozenset({"cleaning", "returning"}),
}

#: States that mean Home Assistant cannot currently see the device.
UNREACHABLE = frozenset({"unavailable", "unknown"})


def entity_map(payload: dict[str, Any]) -> dict[str, str]:
    """`canonical id → entity id`, read from the raw bridge payload.

    Deliberately built from the *raw* payload rather than from the normalized
    snapshot, because the normalizer strips entity ids on the way out and must
    go on doing so: no Home Assistant entity id may reach a browser, and the
    only reason this side needs them is to look a state up by one.

    A bridge that does not publish `entity_id` on its items yields an empty map,
    and an empty map turns the whole overlay off.
    """
    mapping: dict[str, str] = {}
    groups, _ = _container(payload)
    for raw in groups:
        identifier = normalize._text(normalize._first(raw, "id", "key"))
        entity = normalize._text(raw.get("entity_id"))
        if identifier and entity and "." in entity:
            mapping[identifier] = entity
    return mapping


def _container(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Every item in the payload, whether it is grouped or flat."""
    items: list[dict[str, Any]] = []
    raw_groups = payload.get("groups")
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if isinstance(group, dict):
                items.extend(
                    entry for entry in normalize._as_items(group.get("items")) if entry
                )
    items.extend(entry for entry in normalize._as_items(payload.get("items")) if entry)
    return items, bool(items)


def overlay(
    snapshot: ResourceSnapshot,
    mapping: dict[str, str],
    states: dict[str, dict[str, Any]],
) -> ResourceSnapshot:
    """Refresh each switch position from Home Assistant's own state.

    Only `toggle` items are touched, and only where every one of these holds:
    the bridge gave the item an entity id, Home Assistant knows that entity, the
    entity's domain is one this module understands, and the state is not one of
    the unreachable ones. Anything else keeps the bridge's value.
    """
    if not mapping or not states:
        return snapshot

    for item in snapshot.items:
        if item.kind != "toggle":
            continue
        entity = mapping.get(item.id)
        if entity is None:
            continue
        current = states.get(entity)
        if not isinstance(current, dict):
            continue
        raw = normalize._text(current.get("state"))
        if raw is None or raw.lower() in UNREACHABLE:
            # Home Assistant is answering "I cannot see it". The bridge already
            # said something about this device — very likely the same thing —
            # and its sentence is the one with a Hebrew reason attached.
            continue
        known = ON_STATES.get(entity.split(".", 1)[0])
        if known is None:
            continue
        value = raw.lower() in known
        if value == item.value:
            continue
        item.value = value
        item.display = humanise(value, item)

    return snapshot
