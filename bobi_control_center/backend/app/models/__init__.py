"""Typed models for the Bobi Control Center API.

Phase 2 has a single model family: the bridge contract in `bridge.py`, which
both adapters satisfy.
"""

from .bridge import (
    DEVICE_SCOPES,
    BridgeCapabilities,
    BridgeCapability,
    BridgeDevice,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeIssue,
    BridgeModel,
    BridgeProbe,
    BridgeRule,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTask,
    BridgeTasks,
    BridgeUser,
    BridgeUsers,
    CapabilityToggle,
    ConnectionInfo,
    DeviceLimits,
    DiagnosticCheck,
    ProbeUnderstanding,
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
    "BridgeModel",
    "BridgeProbe",
    "BridgeRule",
    "BridgeRules",
    "BridgeShabbat",
    "BridgeStatus",
    "BridgeTask",
    "BridgeTasks",
    "BridgeUser",
    "BridgeUsers",
    "CapabilityToggle",
    "ConnectionInfo",
    "DeviceLimits",
    "DiagnosticCheck",
    "ProbeUnderstanding",
    "ShabbatProfile",
    "StatusComponent",
]
