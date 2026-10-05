"""Read-only Home Assistant discovery surface for the Bobi Next setup wizard.

The wizard never asks the user for a Home Assistant token or entity ids. On a
managed Home Assistant installation the Supervisor injects the token into the
App process; this router only returns aggregate counts, not household names.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException

from .ha_discovery import DiscoveryError, HomeAssistantDiscoveryClient


def create_setup_discovery_router(
    *,
    api_base_url: str,
    token: str,
    timeout_seconds: float = 30.0,
) -> APIRouter:
    router = APIRouter(prefix="/api/next/setup", tags=["bobi-next-setup"])

    @router.post("/home-scan")
    async def home_scan() -> dict[str, Any]:
        if not token:
            raise HTTPException(status_code=503, detail="home_assistant_access_unavailable")

        client = HomeAssistantDiscoveryClient(
            api_base_url=api_base_url,
            token=token,
            timeout_seconds=timeout_seconds,
        )
        try:
            snapshot = await client.snapshot()
            devices = snapshot.semantic_devices()
        except DiscoveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            await client.aclose()

        capabilities = sorted(
            {
                capability
                for device in devices
                for capability in device.capabilities
                if capability
            }
        )
        domains: Counter[str] = Counter(
            entity.domain
            for device in devices
            for entity in device.entities
            if entity.domain
        )
        return {
            "ok": True,
            "devices": len(devices),
            "available_devices": sum(1 for device in devices if device.available),
            "entities": sum(len(device.entities) for device in devices),
            "areas": len(snapshot.areas),
            "capabilities": len(capabilities),
            "domains": [
                {"domain": domain, "entities": count}
                for domain, count in sorted(domains.items())
            ],
        }

    return router
