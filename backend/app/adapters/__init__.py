"""Adapters — the only place allowed to know about Home Assistant."""

from .base import HomeAssistantAdapter
from .mock import MockHomeAssistantAdapter
from .real import RealHomeAssistantAdapter

__all__ = [
    "HomeAssistantAdapter",
    "MockHomeAssistantAdapter",
    "RealHomeAssistantAdapter",
]
