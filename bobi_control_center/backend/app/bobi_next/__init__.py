"""Bobi Next generic core.

This package is intentionally isolated from the production Bobi bridge.  It is
safe to import and test without registering routes, calling Home Assistant
services, or sending WhatsApp messages.
"""

from .models import ActionPlan, DeviceRecord, EntityRecord, TargetResolution

__all__ = ["ActionPlan", "DeviceRecord", "EntityRecord", "TargetResolution"]
