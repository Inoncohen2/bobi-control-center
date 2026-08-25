"""Dependency wiring.

The concrete adapter is chosen exactly once, here. Nothing else in the codebase
imports :class:`MockHomeAssistantAdapter` or ``RealHomeAssistantAdapter`` — which
is what keeps Phase 2 to a one-line change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.adapters import (
    HomeAssistantAdapter,
    MockHomeAssistantAdapter,
    RealHomeAssistantAdapter,
)
from app.config import Settings
from app.services import BobiService, PreviewStore


def build_adapter(settings: Settings) -> HomeAssistantAdapter:
    if settings.adapter == "real":
        return RealHomeAssistantAdapter(
            base_url=settings.ha_url or None,
            token=settings.ha_token or None,
        )
    return MockHomeAssistantAdapter()


def build_service(settings: Settings) -> BobiService:
    return BobiService(build_adapter(settings), PreviewStore())


def get_service(request: Request) -> BobiService:
    """Return the process-wide service built during app startup."""
    return request.app.state.service


ServiceDep = Annotated[BobiService, Depends(get_service)]
