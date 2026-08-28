"""Showing a camera without handing the browser a way into the house.

A picture is the one thing this application returns that is not JSON, and it is
the one read whose upstream URL carries a working credential. So most of what
follows asserts refusals: which ids may be resolved, what never appears in a
response, and what happens when the camera is simply not there — which, on the
install this was written against, is what happens every time.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters import MockHomeAssistantAdapter
from app.errors import BobiError, NotFoundError
from app.mock.management import DEFAULT_RESOURCE_PAYLOADS
from app.services import camera
from tests.conftest import TEST_TOKEN

CATALOGUE = {
    "groups": [
        {
            "id": "devices",
            "items": [
                {"id": "cam_lia", "kind": "readonly", "entity_id": "camera.lia_local"},
                {"id": "laundry", "kind": "toggle", "entity_id": "switch.laundry_1"},
                {"id": "nameless", "kind": "toggle"},
            ],
        }
    ],
    "items": [],
}


# --- which camera may be fetched --------------------------------------------
def test_a_canonical_id_resolves_to_the_entity_the_bridge_named() -> None:
    assert camera.resolve(CATALOGUE, "cam_lia") == "camera.lia_local"


def test_an_id_the_bridge_never_published_is_refused() -> None:
    with pytest.raises(NotFoundError):
        camera.resolve(CATALOGUE, "cam_neighbour")


def test_a_canonical_id_that_is_not_a_camera_is_refused() -> None:
    """The one that stops this being a general image proxy.

    `laundry` is a real id in the household's own catalogue — it is simply a
    switch. Without the domain check, any id the bridge published could be sent
    to `/camera_proxy`.
    """
    with pytest.raises(NotFoundError):
        camera.resolve(CATALOGUE, "laundry")


def test_an_entity_id_cannot_be_passed_through_as_a_canonical_id() -> None:
    """There is no branch that accepts one, so it resolves to nothing."""
    with pytest.raises(NotFoundError):
        camera.resolve(CATALOGUE, "camera.lia_local")


def test_the_same_answer_is_given_however_the_id_is_wrong() -> None:
    """A caller guessing ids learns only that the guess was wrong."""
    unknown = pytest.raises(NotFoundError)
    with unknown as missing:
        camera.resolve(CATALOGUE, "cam_neighbour")
    with pytest.raises(NotFoundError) as wrong_domain:
        camera.resolve(CATALOGUE, "laundry")

    assert missing.value.message == wrong_domain.value.message


# --- the real adapter -------------------------------------------------------
async def test_the_image_is_fetched_with_the_supervisor_token(
    make_real_adapter, recorded_requests
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if "camera_proxy" in request.url.path:
            return httpx.Response(200, content=b"\x89PNG-bytes", headers={"content-type": "image/png"})
        return httpx.Response(200, json={"service_response": CATALOGUE})

    adapter = make_real_adapter(handler)
    frame = await adapter.camera_frame("cam_lia")
    await adapter.aclose()

    assert frame.image == b"\x89PNG-bytes"
    assert frame.content_type == "image/png"

    fetch = recorded_requests[-1]
    assert fetch.method == "GET"
    assert fetch.url.path.endswith("/camera_proxy/camera.lia_local")
    assert fetch.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
    # The credential Home Assistant publishes on the entity is never used, so
    # it is never anywhere it could leak from.
    assert "token" not in fetch.url.params


async def test_a_camera_that_is_not_there_is_reported_rather_than_started(
    make_real_adapter, recorded_requests
) -> None:
    """The only path the real house can currently exercise.

    `camera.lia_local` answers 500 because the camera is unplugged. That has to
    become a message a person can read, and it must not become an attempt to
    switch anything on.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if "camera_proxy" in request.url.path:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json={"service_response": CATALOGUE})

    adapter = make_real_adapter(handler)
    with pytest.raises(BobiError) as raised:
        await adapter.camera_frame("cam_lia")
    await adapter.aclose()

    assert raised.value.code == "camera_unavailable"
    assert raised.value.message == "המצלמה אינה זמינה כרגע"
    # Nothing was turned on to find out.
    assert all(r.method == "GET" or "bobi_cc_devices" in r.url.path for r in recorded_requests)


async def test_no_image_is_requested_for_an_id_that_is_not_a_camera(
    make_real_adapter, recorded_requests
) -> None:
    """The refusal happens before Home Assistant is asked for a picture."""
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"service_response": CATALOGUE})

    adapter = make_real_adapter(handler)
    with pytest.raises(NotFoundError):
        await adapter.camera_frame("laundry")
    await adapter.aclose()

    assert not any("camera_proxy" in r.url.path for r in recorded_requests)


# --- the route --------------------------------------------------------------
def test_the_route_returns_bytes_and_refuses_to_let_them_be_cached(client) -> None:
    response = client.get("/api/bobi/cameras/cam_lia/snapshot")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert "no-store" in response.headers["cache-control"]
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_route_never_names_the_entity_behind_the_camera(client) -> None:
    response = client.get("/api/bobi/cameras/cam_lia/snapshot")

    body = response.content
    for header in response.headers.values():
        assert "camera." not in header
    assert b"camera.lia_local" not in body
    assert b"lia_local" not in body


def test_an_entity_id_in_the_path_is_rejected_by_shape(client) -> None:
    """A dot is not part of a canonical id, so this never reaches a lookup."""
    assert client.get("/api/bobi/cameras/camera.lia_local/snapshot").status_code == 422


def test_a_device_that_is_not_a_camera_is_a_plain_404(client) -> None:
    assert client.get("/api/bobi/cameras/laundry/snapshot").status_code == 404


def test_every_camera_the_double_publishes_can_be_fetched() -> None:
    """The double must not drift into publishing a camera nothing can show."""
    import asyncio

    adapter = MockHomeAssistantAdapter()
    cameras = [
        item["id"]
        for item in DEFAULT_RESOURCE_PAYLOADS["devices"]["items"]
        if str(item.get("entity_id", "")).startswith("camera.")
    ]

    assert cameras, "the double publishes no camera at all"
    for camera_id in cameras:
        assert asyncio.run(adapter.camera_frame(camera_id)).image
