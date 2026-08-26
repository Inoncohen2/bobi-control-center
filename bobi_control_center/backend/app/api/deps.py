"""Dependency wiring.

The concrete adapter is chosen exactly once, here, from settings. Nothing else
in the codebase imports a concrete adapter.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request

from app.adapters import (
    HomeAssistantAdapter,
    MockHomeAssistantAdapter,
    RealHomeAssistantAdapter,
)
from app.auth import actor_for
from app.config import Settings
from app.services.audit import build_trail
from app.services.manage import ManagementService
from app.services.roles import Actor

logger = logging.getLogger("bobi")


def build_adapter(settings: Settings) -> HomeAssistantAdapter:
    """Select the adapter.

    With `BOBI_ADAPTER=auto` (the default) the presence of SUPERVISOR_TOKEN
    decides: inside a Home Assistant app it is injected, so the real bridge is
    used; anywhere else the mock keeps local development working.
    """
    if settings.resolved_adapter == "real":
        if not settings.has_supervisor_token:
            # Explicitly requested but unusable — say so rather than making
            # unauthenticated requests that would all fail with 401.
            logger.warning(
                "BOBI_ADAPTER=real but SUPERVISOR_TOKEN is missing; falling back to mock data."
            )
            return MockHomeAssistantAdapter()
        logger.info("Using the real Home Assistant bridge (read-only).")
        return RealHomeAssistantAdapter(settings)

    logger.info("Using mock data — no Home Assistant connection.")
    return MockHomeAssistantAdapter()


def build_management(
    adapter: HomeAssistantAdapter, settings: Settings | None = None
) -> ManagementService:
    """Wrap whatever write bridge the adapter declares — usually none.

    The service holds the previews and the audit trail, so it must be one
    per process rather than one per request: a preview created by one request
    has to still be there when the next one confirms it.

    The trail is given the app's persistent directory, so the record of what
    was changed outlives a restart — which is when someone is most likely to
    want to read it.
    """
    bridge = adapter.management_bridge()
    if bridge is None:
        logger.info("No Home Assistant write bridge declared — management is unavailable.")
    trail = build_trail(settings.data_dir if settings else None)
    if trail.path is not None:
        logger.info("Management trail at %s", trail.path)
    return ManagementService(bridge, trail)


def get_adapter(request: Request) -> HomeAssistantAdapter:
    """Return the process-wide adapter built at app construction."""
    return request.app.state.adapter


def get_management(request: Request) -> ManagementService:
    """Return the process-wide management service built at app construction."""
    return request.app.state.management


def get_actor(request: Request) -> Actor:
    """Who is asking, resolved from the session rather than from the request body.

    Every write route depends on this. A route that did not would fall to the
    service's own default, which is a viewer — so forgetting it costs the
    ability to write, never grants it.
    """
    return actor_for(request)


AdapterDep = Annotated[HomeAssistantAdapter, Depends(get_adapter)]
ManagementDep = Annotated[ManagementService, Depends(get_management)]
ActorDep = Annotated[Actor, Depends(get_actor)]
