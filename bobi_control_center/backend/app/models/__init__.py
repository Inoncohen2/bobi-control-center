"""Typed models for the Bobi Control Center API.

Phase 2 has a single model family: the canonical contract in `bridge.py`, which
`app/services/normalize.py` maps the raw bridge response onto.
"""

from .bridge import (
    DEVICE_SCOPES,
    BridgeCapabilities,
    BridgeCapability,
    BridgeDevice,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeIssue,
    BridgeProbe,
    BridgeRule,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTask,
    BridgeTasks,
    BridgeUser,
    BridgeUsers,
    CanonicalModel,
    CapabilityToggle,
    ConnectionInfo,
    DeviceLimits,
    DiagnosticCheck,
    ShabbatProfile,
    StatusComponent,
)

__all__ = [
    "DEVICE_SCOPES",
    "BridgeCapabilities",
    "BridgeCapability",
    "BridgeDevice",
    "BridgeDevices",
    "BridgeDiagnostics",
    "BridgeIssue",
    "BridgeProbe",
    "BridgeRule",
    "BridgeRules",
    "BridgeShabbat",
    "BridgeStatus",
    "BridgeTask",
    "BridgeTasks",
    "BridgeUser",
    "BridgeUsers",
    "CanonicalModel",
    "CapabilityToggle",
    "ConnectionInfo",
    "DeviceLimits",
    "DiagnosticCheck",
    "ShabbatProfile",
    "StatusComponent",
]
