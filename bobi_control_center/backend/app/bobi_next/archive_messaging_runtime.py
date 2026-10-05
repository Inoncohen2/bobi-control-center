"""Archive-aware Bobi Next messaging runtime.

This composition layer keeps the proven provider-neutral messaging runtime intact
while wiring Bobi's private archive into WhatsApp. It is still fully opt-in via
the application-level ``next_messaging_enabled`` gate.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from .archive_subsystem import ArchiveSubsystem
from .conversation_handler import build_conversation_handler
from .media_analyzers import MediaAnalyzerRegistry
from .media_pipeline import MediaPipeline
from .messaging import MessageStore
from .messaging_runtime import (
    BobiNextMessagingRuntime,
    MessagingRuntimeStatus,
    ProviderBoundary,
)
from .setup_store import MessagingProvider
from .understanding import ResilientUnderstandingProvider
from .waha_adapter import WahaMediaLoader, WahaTransport
from .waha_outbound_media import WahaOutboundMediaTransport

logger = logging.getLogger("bobi.next.archive-messaging")


def _provider_storage_key(provider_key: str) -> str:
    return hashlib.sha256(provider_key.encode()).hexdigest()[:20]


class ArchiveMessagingRuntime(BobiNextMessagingRuntime):
    """Messaging runtime with private document capture and outbound delivery."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.archive = ArchiveSubsystem(self.data_dir)
        self.archive_tasks: dict[str, asyncio.Task[None]] = {}

    def _waha_boundary(
        self,
        provider: MessagingProvider,
        *,
        understanding: ResilientUnderstandingProvider,
        analyzers: MediaAnalyzerRegistry,
    ) -> ProviderBoundary:
        if not provider.endpoint.strip():
            raise ValueError("waha_endpoint_required")
        api_key = ""
        if provider.secret_ref:
            api_key = self.secrets.resolve(provider.secret_ref)

        transport = WahaTransport(
            base_url=provider.endpoint,
            session=provider.session or "default",
            api_key=api_key,
            engine=provider.engine or "GOWS",
        )
        media_pipeline = MediaPipeline(
            loader=WahaMediaLoader(
                base_url=provider.endpoint,
                api_key=api_key,
            ),
            analyzer_for=analyzers.get,
        )
        messages = MessageStore(
            self.data_dir
            / f"bobi-next-messages-{_provider_storage_key(provider.provider_key)}.db"
        )
        handler = build_conversation_handler(
            understanding=understanding,
            list_devices=self.list_devices,
            policy_for=self.policy_for,
            ha=self.ha,
            memory=self.memory,
            requests=self.requests,
            pending_approvals=self.pending_approvals,
            approval_tokens=self.approvals,
            schedules=self.schedules,
            conditional_rules=self.conditional_rules,
            media_pipeline=media_pipeline,
            archive_capture=self.archive.capture,
            activity=self.activity,
            undo_requests=self.undo_requests,
            dry_run=self.dry_run,
        )
        return ProviderBoundary(provider, messages, transport, handler)

    async def _archive_worker(
        self,
        provider_key: str,
        boundary: ProviderBoundary,
        stop_event: asyncio.Event,
    ) -> None:
        transport = boundary.transport
        if not isinstance(transport, WahaTransport):
            return
        outbound = WahaOutboundMediaTransport(
            base_url=transport.base_url,
            session=transport.session,
            api_key=transport.api_key,
        )
        owner_token = f"bobi-next-archive-media:{provider_key}"
        while not stop_event.is_set():
            try:
                result = await self.archive.process_next(
                    provider_key,
                    outbound,
                    owner_token=owner_token,
                    now_ts=int(time.time()),
                )
            except Exception as exc:
                # Archive failures must not kill messaging or leak document data.
                logger.warning(
                    "Bobi Next archive worker error provider=%s type=%s",
                    provider_key,
                    type(exc).__name__,
                )
                await self._idle(stop_event)
                continue
            if result is None:
                await self._idle(stop_event)

    async def start(self) -> MessagingRuntimeStatus:
        status = await super().start()
        if not status.ready or self.stop_event is None:
            return status

        for provider_key, boundary in self.boundaries.items():
            existing = self.archive_tasks.get(provider_key)
            if existing is not None and not existing.done():
                continue
            if not isinstance(boundary.transport, WahaTransport):
                continue
            self.archive_tasks[provider_key] = asyncio.create_task(
                self._archive_worker(provider_key, boundary, self.stop_event),
                name=f"bobi-next-archive-{_provider_storage_key(provider_key)}",
            )
        return status

    async def aclose(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        tasks = list(self.archive_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.archive_tasks.clear()
        await super().aclose()
        self.archive.close()
