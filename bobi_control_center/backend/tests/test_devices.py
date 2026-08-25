"""Device mapping: raw entities in, friendly Bobi devices out."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.mock.entities import MOCK_ENTITIES
from app.models import DeviceCategory
from app.services.devices import to_device, to_devices


def test_device_list_groups_rooms_and_categories(client: TestClient) -> None:
    body = client.get("/api/bobi/devices").json()

    assert body["devices"]
    assert set(body["rooms"]) == {"סלון", "מטבח", "חדר הורים", "חדר בנות", "חוץ"}
    assert "climate" in body["categories"]


def test_device_exposes_friendly_fields_and_hides_entity_id_behind_advanced(
    client: TestClient,
) -> None:
    device = client.get("/api/bobi/devices/living_room_ac").json()

    assert device["display_name"] == "מזגן סלון"
    assert device["room"] == "סלון"
    assert device["category"] == "climate"
    assert "המזגן בסלון" in device["aliases"]
    assert "set_temperature" in device["capabilities"]
    # The technical id exists, but only inside the advanced block.
    assert device["advanced"]["entity_id"] == "climate.demo_living_room_ac"


def test_unavailable_device_is_marked(client: TestClient) -> None:
    device = client.get("/api/bobi/devices/lia_camera").json()
    assert device["available"] is False
    assert device["state"] == "unavailable"
    assert device["state_label"] == "לא זמין"


def test_unknown_device_returns_structured_error(client: TestClient) -> None:
    response = client.get("/api/bobi/devices/does_not_exist")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["message"]
    assert "Traceback" not in body["message"]


def test_boiler_is_its_own_category_even_though_it_is_a_switch() -> None:
    entity = next(e for e in MOCK_ENTITIES if e.entity_id == "switch.demo_boiler")
    assert to_device(entity).category is DeviceCategory.BOILER


def test_every_entity_maps_to_a_unique_device_id() -> None:
    devices = to_devices(MOCK_ENTITIES)
    ids = [device.id for device in devices]
    assert len(ids) == len(set(ids))
    assert all(not device.id.startswith("demo_") for device in devices)


def test_sensor_state_label_includes_its_unit() -> None:
    devices = {d.id: d for d in to_devices(MOCK_ENTITIES)}
    assert devices["outdoor_temperature"].state_label == "31.2°C"
