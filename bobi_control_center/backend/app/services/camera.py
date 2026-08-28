"""Which camera a request is allowed to fetch, and nothing wider.

## Why this is its own module

Showing a camera means the browser asking for a picture, and a picture lives
behind an entity id and a credential — the two things this application has
spent every other module keeping out of the browser. So the request names a
*canonical id* (`cam_lia`), exactly as every other screen does, and this module
is the only place that turns one into an entity.

That turn is a whitelist, not a lookup. The mapping comes from the bridge's own
device catalogue, so a request can only ever reach a camera the household
already published; and the resolved entity must be in the `camera` domain, so a
canonical id pointing at a light or a switch cannot be used to make this
endpoint fetch something that is not a camera. Both conditions must hold. A
failure to meet either is a plain 404 — the same answer for "no such camera"
and "that id is not a camera", because the difference is not the caller's
business.

## What this deliberately does not do

It does not accept an entity id. There is no parameter for one and no branch
that would use one, so no caller — including a future one written in a hurry —
can pass `camera.anything` through to Home Assistant.

It never touches the camera's own `access_token`. Home Assistant publishes one
on the entity as `entity_picture`, and it is a working credential for that
stream: anyone holding it can watch the camera for as long as it lives. The
image is fetched with the Supervisor token in an `Authorization` header
instead, server-side, and the bytes are what reaches the browser.
"""

from __future__ import annotations

from typing import Any

from app.errors import NotFoundError
from app.services.live_state import entity_map

#: The one domain this endpoint may fetch from.
CAMERA_DOMAIN = "camera"

#: Said for both "no such camera" and "that id is not a camera". A caller who
#: guessed an id learns only that the guess was wrong.
UNKNOWN = "לא נמצאה מצלמה כזו"


def resolve(payload: dict[str, Any], camera_id: str) -> str:
    """`cam_lia` → `camera.lia_local`, or raise.

    `payload` is the *raw* bridge catalogue, because that is the only place the
    entity id survives: the normalizer strips it on the way to a client and must
    go on doing so.
    """
    entity = entity_map(payload).get(camera_id.strip())
    if entity is None:
        raise NotFoundError(UNKNOWN, details={"camera": camera_id})

    domain, _, rest = entity.partition(".")
    if domain != CAMERA_DOMAIN or not rest:
        # The bridge named this id, but it is not a camera. Refusing here is
        # what stops the endpoint being a general-purpose image proxy for
        # whatever else the catalogue happens to carry.
        raise NotFoundError(UNKNOWN, details={"camera": camera_id})

    return entity
