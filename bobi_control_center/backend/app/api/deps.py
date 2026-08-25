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
from app.config import Settings

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


def get_adapter(request: Request) -> HomeAssistantAdapter:
    """Return the process-wide adapter built at app construction."""
    return request.app.state.adapter


AdapterDep = Annotated[HomeAssistantAdapter, Depends(get_adapter)]
