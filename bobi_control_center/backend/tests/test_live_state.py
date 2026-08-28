"""The split: catalogue from the bridge, switch positions from Home Assistant.

These carry more than usual weight. The live half cannot be exercised against
the real house from a test run, so what follows is the whole of the evidence
that it behaves — including, deliberately, every way it is meant to *decline*
to act. A read path that guesses wrong about a switch is worse than one that
does nothing, so most of these assert that nothing happened.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.real_management import RealManagementBridge
from app.errors import UpstreamError
from app.models.manage import ObservedState
from app.services.live_state import ON_STATES, entity_map, overlay
from app.services.resource_normalize import normalize_resource

pytestmark = pytest.mark.anyio


def catalogue(**overrides: Any) -> dict[str, Any]:
    """The devices payload, shaped as the live bridge sends it."""
    items = overrides.pop("items", None) or [
        {"id": "salon", "label": "אור סלון", "kind": "toggle", "value": False, "display": "off",
         "controllable": True, "operations": ["power"], "entity_id": "light.tvrh_mtg_2",
         "detail": {"domain": "light"}},
        {"id": "robi", "label": "רובי", "kind": "toggle", "value": False, "display": "docked",
         "controllable": True, "operations": ["start", "stop"],
         "entity_id": "vacuum.rockrobo_v1_647e_robot_cleaner"},
        {"id": "ac_salon_temperature", "label": "מזגן סלון — יעד", "kind": "number", "value": 24,
         "controllable": True, "operations": ["temperature"],
         "entity_id": "climate.150633094867667_climate"},
    ]
    return {"available": True, "writes_enabled": True,
            "groups": [{"id": "devices", "label": "מכשירים", "items": items}], **overrides}


def states(**pairs: str) -> dict[str, dict[str, Any]]:
    return {entity: {"entity_id": entity, "state": state} for entity, state in pairs.items()}


# --- the mapping ------------------------------------------------------------
def test_the_map_is_built_from_the_raw_payload() -> None:
    """Not from the snapshot: the normalizer strips entity ids on the way out.

    That stripping is the property that keeps Home Assistant entity ids out of
    a browser, and it must go on happening — so the only place the id can still
    be read is the payload the bridge sent.
    """
    mapping = entity_map(catalogue())

    assert mapping == {
        "salon": "light.tvrh_mtg_2",
        "robi": "vacuum.rockrobo_v1_647e_robot_cleaner",
        "ac_salon_temperature": "climate.150633094867667_climate",
    }


def test_no_entity_id_reaches_the_client_even_now() -> None:
    """The whole reason the map is built separately."""
    snapshot = normalize_resource("devices", catalogue())
    rendered = snapshot.model_dump_json()

    assert "light.tvrh_mtg_2" not in rendered
    assert "entity_id" not in rendered


def test_a_bridge_that_publishes_no_entity_ids_yields_no_map() -> None:
    """Which is what turns the overlay off, rather than turning it wrong."""
    payload = catalogue(items=[
        {"id": "salon", "label": "אור סלון", "kind": "toggle", "value": False,
         "controllable": True, "operations": ["power"]},
    ])

    assert entity_map(payload) == {}


# --- the overlay ------------------------------------------------------------
def test_a_switch_follows_home_assistant() -> None:
    snapshot = normalize_resource("devices", catalogue())
    overlay(snapshot, entity_map(catalogue()), states(**{"light.tvrh_mtg_2": "on"}))

    salon = next(item for item in snapshot.items if item.id == "salon")
    assert salon.value is True
    assert salon.display == "פעיל"


def test_the_group_sees_the_same_refreshed_item() -> None:
    """`items` is a flattened view of the groups, not a copy of them.

    If it were a copy, every one of these tests would pass and the screen —
    which renders groups — would show the stale value anyway.
    """
    snapshot = normalize_resource("devices", catalogue())
    overlay(snapshot, entity_map(catalogue()), states(**{"light.tvrh_mtg_2": "on"}))

    grouped = next(item for item in snapshot.groups[0].items if item.id == "salon")
    assert grouped.value is True


def test_a_docked_vacuum_is_not_running() -> None:
    """The reason `ON_STATES` is a table and not `state != "off"`.

    A docked vacuum's state is "docked", which is not "off" — so the simple
    rule would have drawn its switch as on, and a household would have been
    told the vacuum was cleaning while it sat on its charger.
    """
    snapshot = normalize_resource("devices", catalogue())
    entity = "vacuum.rockrobo_v1_647e_robot_cleaner"

    overlay(snapshot, entity_map(catalogue()), states(**{entity: "docked"}))
    assert next(i for i in snapshot.items if i.id == "robi").value is False

    overlay(snapshot, entity_map(catalogue()), states(**{entity: "cleaning"}))
    assert next(i for i in snapshot.items if i.id == "robi").value is True


def test_a_climate_mode_is_a_switch_position() -> None:
    """A climate entity's state is its mode, and every mode but "off" is on."""
    payload = catalogue(items=[
        {"id": "ac_salon", "label": "מזגן סלון", "kind": "toggle", "value": False,
         "controllable": True, "operations": ["power"],
         "entity_id": "climate.150633094867667_climate"},
    ])
    snapshot = normalize_resource("devices", payload)
    overlay(snapshot, entity_map(payload), states(**{"climate.150633094867667_climate": "cool"}))

    assert snapshot.items[0].value is True


# --- every way it declines to act -------------------------------------------
@pytest.mark.parametrize("raw", ["unavailable", "unknown"])
def test_an_unreachable_entity_keeps_the_bridge_answer(raw: str) -> None:
    """Home Assistant saying "I cannot see it" is not a switch position.

    The bridge already said something about this device, and its sentence is
    the one with a Hebrew reason attached to it.
    """
    payload = catalogue(items=[
        {"id": "mosquito", "label": "קוטל יתושים", "kind": "toggle", "value": True,
         "display": "פעיל", "controllable": True, "operations": ["power"],
         "entity_id": "switch.mnvrt_lylh_lyh_socket_1"},
    ])
    snapshot = normalize_resource("devices", payload)
    overlay(snapshot, entity_map(payload), states(**{"switch.mnvrt_lylh_lyh_socket_1": raw}))

    assert snapshot.items[0].value is True
    assert snapshot.items[0].display == "פעיל"


def test_a_domain_this_module_does_not_know_is_left_alone() -> None:
    """Adding a device class nobody thought about cannot produce a wrong switch."""
    payload = catalogue(items=[
        {"id": "gate", "label": "שער", "kind": "toggle", "value": False,
         "controllable": True, "operations": ["power"], "entity_id": "cover.front_gate"},
    ])
    assert "cover" not in ON_STATES

    snapshot = normalize_resource("devices", payload)
    overlay(snapshot, entity_map(payload), states(**{"cover.front_gate": "open"}))

    assert snapshot.items[0].value is False


def test_an_entity_home_assistant_never_heard_of_is_left_alone() -> None:
    snapshot = normalize_resource("devices", catalogue())
    overlay(snapshot, entity_map(catalogue()), states(**{"light.somewhere_else": "on"}))

    assert next(i for i in snapshot.items if i.id == "salon").value is False


def test_only_switches_are_refreshed() -> None:
    """A temperature is not a switch position, and working one out from a raw
    state would mean copying the whole capability model into this side."""
    snapshot = normalize_resource("devices", catalogue())
    overlay(
        snapshot,
        entity_map(catalogue()),
        {"climate.150633094867667_climate": {"state": "cool", "attributes": {"temperature": 19}}},
    )

    assert next(i for i in snapshot.items if i.id == "ac_salon_temperature").value == 24


def test_an_empty_state_reading_changes_nothing() -> None:
    snapshot = normalize_resource("devices", catalogue())
    overlay(snapshot, entity_map(catalogue()), {})

    assert next(i for i in snapshot.items if i.id == "salon").value is False


# --- the wiring -------------------------------------------------------------
class _Adapter:
    """Enough of the real adapter to drive the bridge's read path."""

    def __init__(self, payload: dict[str, Any], states: Any) -> None:
        self._payload_value = payload
        self._states = states
        self.payload_calls = 0
        self.state_calls = 0

    async def _payload(self, service: str, data: Any = None) -> dict[str, Any]:
        self.payload_calls += 1
        return self._payload_value

    async def fetch_states(self) -> dict[str, dict[str, Any]]:
        self.state_calls += 1
        if isinstance(self._states, Exception):
            raise self._states
        return self._states


async def test_the_catalogue_is_rendered_once_for_a_burst_of_reads() -> None:
    """The saving. Without this the split is simply one more round trip."""
    adapter = _Adapter(catalogue(), states(**{"light.tvrh_mtg_2": "on"}))
    bridge = RealManagementBridge(adapter)  # type: ignore[arg-type]

    for _ in range(5):
        snapshot = await bridge.resource_snapshot("devices")

    assert adapter.payload_calls == 1
    assert adapter.state_calls == 5
    # …and the fifth read is still fresh.
    assert next(i for i in snapshot.items if i.id == "salon").value is True


async def test_unreachable_states_degrade_to_the_bridge_rather_than_to_an_error() -> None:
    """The behaviour that existed before this split, which is a working screen."""
    adapter = _Adapter(catalogue(), UpstreamError("Home Assistant לא הגיב בזמן"))
    bridge = RealManagementBridge(adapter)  # type: ignore[arg-type]

    snapshot = await bridge.resource_snapshot("devices")

    assert snapshot.available is True
    assert next(i for i in snapshot.items if i.id == "salon").value is False


async def test_a_family_that_is_not_devices_is_never_split() -> None:
    """Every other family's snapshot *is* its state, so splitting it would buy
    nothing and cost a round trip — and would reuse a stale catalogue."""
    adapter = _Adapter({"available": True, "groups": []}, {})
    bridge = RealManagementBridge(adapter)  # type: ignore[arg-type]

    await bridge.resource_snapshot("helpers")
    await bridge.resource_snapshot("helpers")

    assert adapter.payload_calls == 2
    assert adapter.state_calls == 0


async def test_a_commit_throws_the_catalogue_away() -> None:
    """The one moment a cached catalogue is certainly wrong.

    A switch position is refreshed from Home Assistant on every read and so
    survives the cache. A target temperature is a catalogue value: changing one
    and then being shown the old number for the next minute would make the
    write look as though it had never landed.
    """
    adapter = _Adapter(catalogue(), states())
    bridge = RealManagementBridge(adapter)  # type: ignore[arg-type]
    await bridge.resource_snapshot("devices")
    assert adapter.payload_calls == 1

    # What the commit bridge answers does not matter here — only that the
    # cache was dropped on the way in.
    await bridge.apply(
        resource_type="devices",
        operation="temperature",
        resource_id="ac_salon",
        payload={"value": 21},
        observed=ObservedState(resource_id="ac_salon", label=None, values={}),
        request_id="req-12345678",
        preview_token="pt_" + "x" * 32,
    )
    adapter.payload_calls = 1  # the commit call itself is not a catalogue read

    await bridge.resource_snapshot("devices")
    assert adapter.payload_calls == 2
