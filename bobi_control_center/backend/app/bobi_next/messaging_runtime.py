"""Opt-in durable messaging runtime for Bobi Next.

This module composes existing safe boundaries without exposing a new HTTP route:
provider-specific inbox/outbox -> reaction/typing -> trusted media -> semantic AI
-> deterministic Bobi engine -> verified reply.

Each messaging provider owns a separate durable queue/worker. Bobi memory,
request ledger, schedules, activity and approval state are installation-wide so
the same user can keep context across providers without allowing one provider's
transport to consume another provider's messages.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .activity import ActivityLedger
from .activity_runtime import ActivityRecordingHAClient, UndoRequestStore
from .ai_providers import AIProviderStore
from .ai_runtime import AIProviderRuntimeRegistry, AIRuntimeError
from .authorization import ApprovalStore, UserPolicy
from .conditional import ConditionalRuleStore
from .conversation_handler import build_conversation_handler
from .executor import HAControlClient
from .media_analyzers import AudioAnalyzer, ImageAnalyzer, MediaAnalyzerRegistry
from .media_pipeline import MediaPipeline
from .memory import BobiMemory
from .messaging import InboundMessage, MessageStore, MessageTransport, process_next_message
from .models import DeviceRecord
from .pending_approval import PendingApprovalStore
from .request_ledger import RequestLedger
from .scheduler import ScheduleStore
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import MessagingProvider, SetupStore
from .understanding import ResilientUnderstandingProvider
from .waha_adapter import WahaMediaLoader, WahaTransport
from .waha_ingest import IngestResult, ingest_waha_event

logger = logging.getLogger("bobi.next.messaging-runtime")

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]


@dataclass(slots=True)
class ProviderBoundary:
    provider: MessagingProvider
    messages: MessageStore
    transport: MessageTransport
    handler: Callable[[InboundMessage], Awaitable]


@dataclass(slots=True, frozen=True)
class MessagingRuntimeStatus:
    ready: bool
    reason: str
    providers: tuple[str, ...] = ()


def _provider_storage_key(provider_key: str) -> str:
    return hashlib.sha256(provider_key.encode("utf-8")).hexdigest()[:20]


def _reaction_for(message: InboundMessage) -> str:
    """Immediate transport acknowledgement before the expensive brain path."""

    return {
        "voice": "🎧",
        "audio": "🎧",
        "image": "👀",
        "document": "📄",
        "video": "👀",
    }.get(message.kind, "⚡")


class BobiNextMessagingRuntime:
    def __init__(
        self,
        *,
        data_dir: str | Path,
        setup: SetupStore,
        ha: HAControlClient,
        list_devices: DeviceProvider,
        policy_for: PolicyProvider,
        pending_approvals: PendingApprovalStore,
        conditional_rules: ConditionalRuleStore | None = None,
        dry_run: bool = False,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.setup = setup
        self.list_devices = list_devices
        self.policy_for = policy_for
        self.pending_approvals = pending_approvals
        self.conditional_rules = conditional_rules
        self.dry_run = bool(dry_run)
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))

        self.memory = BobiMemory(self.data_dir / "bobi-next-memory.db")
        self.requests = RequestLedger(self.data_dir / "bobi-next-requests.db")
        self.activity = ActivityLedger(self.data_dir / "bobi-next-activity.db")
        self.undo_requests = UndoRequestStore(self.data_dir / "bobi-next-undo-requests.db")
        self.ha = ActivityRecordingHAClient(
            ha,
            activity=self.activity,
            requests=self.requests,
        )
        self.schedules = ScheduleStore(self.data_dir / "bobi-next-schedules.db")
        self.approvals = ApprovalStore(self.data_dir / "bobi-next-approvals.db")
        self.ai_store = AIProviderStore(self.data_dir / "bobi-next-ai.db")
        self.secrets = EncryptedSecretVault(
            self.data_dir / "bobi-next-secrets.db",
            self.data_dir / "bobi-next-secrets.key",
        )
        self.ai = AIProviderRuntimeRegistry(self.ai_store, self.secrets)
        self.boundaries: dict[str, ProviderBoundary] = {}
        self.stop_event: asyncio.Event | None = None
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    def _optional_media_registry(self) -> MediaAnalyzerRegistry:
        audio = None
        image = None
        with suppress(AIRuntimeError):
            audio = AudioAnalyzer(self.ai.audio_provider())
        with suppress(AIRuntimeError):
            image = ImageAnalyzer(self.ai.vision_provider())
        return MediaAnalyzerRegistry(audio=audio, image=image)

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
            activity=self.activity,
            undo_requests=self.undo_requests,
            dry_run=self.dry_run,
        )
        return ProviderBoundary(provider, messages, transport, handler)

    def prepare(self) -> MessagingRuntimeStatus:
        if self._closed:
            return MessagingRuntimeStatus(False, "runtime_closed")
        if self.boundaries:
            return MessagingRuntimeStatus(
                True,
                "already_prepared",
                tuple(sorted(self.boundaries)),
            )

        try:
            primary = self.ai.intent_provider()
        except (AIRuntimeError, SecretVaultError) as exc:
            return MessagingRuntimeStatus(False, str(exc))
        understanding = ResilientUnderstandingProvider(
            primary,
            primary_name=primary.config.provider_key,
        )
        analyzers = self._optional_media_registry()

        failures: list[str] = []
        for provider in self.setup.list_providers(enabled_only=True):
            try:
                if provider.provider_type == "waha":
                    boundary = self._waha_boundary(
                        provider,
                        understanding=understanding,
                        analyzers=analyzers,
                    )
                else:
                    failures.append(f"{provider.provider_key}:unsupported_provider")
                    continue
            except (ValueError, SecretVaultError) as exc:
                failures.append(f"{provider.provider_key}:{exc}")
                continue
            self.boundaries[provider.provider_key] = boundary

        if not self.boundaries:
            reason = "no_supported_messaging_provider"
            if failures:
                reason = f"{reason}:{';'.join(failures)}"
            return MessagingRuntimeStatus(False, reason)
        if failures:
            logger.warning(
                "Bobi Next messaging skipped providers: %s",
                ",".join(failures),
            )
        return MessagingRuntimeStatus(True, "ready", tuple(sorted(self.boundaries)))

    def ingest(self, provider_key: str, event: dict) -> IngestResult:
        boundary = self.boundaries.get(provider_key)
        if boundary is None:
            return IngestResult(False, "provider_not_runtime_enabled")
        return ingest_waha_event(
            event,
            provider_key=provider_key,
            setup=self.setup,
            messages=boundary.messages,
        )

    async def _idle(self, stop_event: asyncio.Event) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)

    async def _worker(
        self,
        provider_key: str,
        boundary: ProviderBoundary,
        stop_event: asyncio.Event,
    ) -> None:
        owner_token = f"bobi-next-message-worker:{provider_key}"
        while not stop_event.is_set():
            try:
                result = await process_next_message(
                    boundary.messages,
                    boundary.transport,
                    boundary.handler,
                    owner_token=owner_token,
                    now_ts=int(time.time()),
                    reaction_for=_reaction_for,
                )
            except Exception as exc:
                # A queue/SQLite/provider boundary failure must not kill other
                # providers or the legacy app. Do not log message content.
                logger.warning(
                    "Bobi Next messaging worker error provider=%s type=%s",
                    provider_key,
                    type(exc).__name__,
                )
                await self._idle(stop_event)
                continue
            if result is None:
                await self._idle(stop_event)

    async def start(self) -> MessagingRuntimeStatus:
        if self.tasks and any(not task.done() for task in self.tasks.values()):
            return MessagingRuntimeStatus(True, "already_running", tuple(sorted(self.tasks)))
        status = self.prepare()
        if not status.ready:
            return status
        self.stop_event = asyncio.Event()
        self.tasks = {
            provider_key: asyncio.create_task(
                self._worker(provider_key, boundary, self.stop_event),
                name=f"bobi-next-messaging-{_provider_storage_key(provider_key)}",
            )
            for provider_key, boundary in self.boundaries.items()
        }
        return MessagingRuntimeStatus(True, "started", tuple(sorted(self.tasks)))

    async def aclose(self) -> None:
        if self._closed:
            return
        if self.stop_event is not None:
            self.stop_event.set()
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        self.stop_event = None

        for boundary in self.boundaries.values():
            boundary.messages.close()
        self.boundaries.clear()
        self.ai_store.close()
        self.secrets.close()
        self.approvals.close()
        self.schedules.close()
        self.undo_requests.close()
        self.activity.close()
        self.requests.close()
        self.memory.close()
        self._closed = True
