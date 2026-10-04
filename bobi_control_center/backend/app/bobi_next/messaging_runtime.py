"""Opt-in durable messaging runtime for Bobi Next.

This module composes existing safe boundaries without exposing a new HTTP route:
provider-specific inbox/outbox -> reaction/typing -> trusted media -> semantic AI
-> deterministic Bobi engine -> verified reply.

Interactive provider events are routed separately from free-form messages. Poll
votes are matched to Bobi-owned poll ids and linked users and are never passed to
AI as command text. Outbound polls are registered only after WAHA returns its
canonical poll message id. Contextual poll selections are reconciled from their
durable vote ledger into a separate exactly-once interaction worker.

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
from collections.abc import Awaitable, Callable, Iterable, Mapping
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
from .interaction_dispatch import (
    InteractionDispatchStore,
    InteractionHandler,
    process_next_interaction,
)
from .media_analyzers import AudioAnalyzer, ImageAnalyzer, MediaAnalyzerRegistry
from .media_pipeline import MediaPipeline
from .memory import BobiMemory
from .messaging import InboundMessage, MessageStore, MessageTransport, process_next_message
from .models import DeviceRecord
from .pending_approval import PendingApprovalStore
from .poll_dispatch_bridge import reconcile_poll_dispatches
from .poll_interactions import PollInteraction, PollInteractionStore
from .poll_outbound import send_registered_poll
from .request_ledger import RequestLedger
from .scheduler import ScheduleStore
from .secret_vault import EncryptedSecretVault, SecretVaultError
from .setup_store import MessagingProvider, SetupStore
from .understanding import ResilientUnderstandingProvider
from .waha_adapter import WahaMediaLoader, WahaTransport
from .waha_ingest import IngestResult, ingest_waha_event
from .waha_interactions import ingest_waha_poll_vote, parse_waha_poll_vote

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


def _interaction_namespace(value: str) -> str:
    key = value.casefold().strip()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"
    if not key or ":" in key or any(ch not in allowed for ch in key):
        return ""
    return key


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
        interaction_handlers: Mapping[str, InteractionHandler] | None = None,
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
        self.interactions = PollInteractionStore(self.data_dir / "bobi-next-interactions.db")
        self.interaction_dispatches = InteractionDispatchStore(
            self.data_dir / "bobi-next-interaction-dispatch.db"
        )
        self.interaction_handlers: dict[str, InteractionHandler] = {}
        for namespace, handler in dict(interaction_handlers or {}).items():
            self.register_interaction_handler(namespace, handler)
        self.ai_store = AIProviderStore(self.data_dir / "bobi-next-ai.db")
        self.secrets = EncryptedSecretVault(
            self.data_dir / "bobi-next-secrets.db",
            self.data_dir / "bobi-next-secrets.key",
        )
        self.ai = AIProviderRuntimeRegistry(self.ai_store, self.secrets)
        self.boundaries: dict[str, ProviderBoundary] = {}
        self.stop_event: asyncio.Event | None = None
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.interaction_task: asyncio.Task[None] | None = None
        self._closed = False

    def register_interaction_handler(
        self,
        namespace: str,
        handler: InteractionHandler,
    ) -> None:
        """Register one deterministic interaction namespace before runtime start."""

        key = _interaction_namespace(namespace)
        if not key:
            raise ValueError("interaction_namespace_invalid")
        if not callable(handler):
            raise TypeError("interaction_handler_not_callable")
        if self.interaction_task is not None and not self.interaction_task.done():
            raise RuntimeError("interaction_runtime_started")
        self.interaction_handlers[key] = handler

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

    async def send_poll(
        self,
        provider_key: str,
        *,
        chat_id: str,
        user_key: str,
        question: str,
        option_keys: dict[str, str],
        multiple_answers: bool = False,
        context_key: str = "",
        expires_ts: int = 0,
        now_ts: int | None = None,
    ) -> PollInteraction:
        """Send and durably register one Bobi-owned WAHA poll.

        Registration happens only after WAHA returns its canonical message id.
        There is intentionally no guessed/fallback poll id. If the process dies
        between network acceptance and registration, a later vote fails closed
        as ``unknown_poll`` rather than being interpreted as an action.
        """

        boundary = self.boundaries.get(provider_key)
        if boundary is None:
            raise KeyError("provider_not_runtime_enabled")
        if not isinstance(boundary.transport, WahaTransport):
            raise TypeError("provider_does_not_support_polls")
        user = self.setup.get_user(user_key)
        if user is None or not user.enabled:
            raise PermissionError("unknown_or_disabled_user")

        return await send_registered_poll(
            boundary.transport,
            self.interactions,
            provider=provider_key,
            chat_id=chat_id,
            user_key=user_key,
            question=question,
            option_keys=option_keys,
            multiple_answers=multiple_answers,
            context_key=context_key,
            expires_ts=expires_ts,
            now_ts=now_ts,
        )

    def ingest(self, provider_key: str, event: dict) -> IngestResult:
        boundary = self.boundaries.get(provider_key)
        if boundary is None:
            return IngestResult(False, "provider_not_runtime_enabled")

        event_name = str(event.get("event") or "")
        if event_name in {"poll.vote", "poll.vote.failed"}:
            parsed = parse_waha_poll_vote(event)
            vote = ingest_waha_poll_vote(
                event,
                provider_key=provider_key,
                setup=self.setup,
                interactions=self.interactions,
            )
            if vote is None or parsed is None:
                return IngestResult(False, "ignored_event")
            # Reconcile even for a duplicate/invalid current event. A previous
            # accepted vote may have been committed immediately before a crash
            # and still need its deterministic continuation queued.
            reconcile_poll_dispatches(
                self.interactions,
                self.interaction_dispatches,
                provider=provider_key,
                poll_message_id=parsed.poll_message_id,
                now_ts=int(time.time()),
            )
            return IngestResult(
                vote.accepted,
                vote.reason,
                duplicate=vote.duplicate,
            )

        return ingest_waha_event(
            event,
            provider_key=provider_key,
            setup=self.setup,
            messages=boundary.messages,
        )

    async def _idle(self, stop_event: asyncio.Event) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)

    def _transport_for(self, provider_key: str) -> MessageTransport:
        boundary = self.boundaries.get(provider_key)
        if boundary is None:
            raise KeyError("provider_not_runtime_enabled")
        return boundary.transport

    async def _interaction_worker(self, stop_event: asyncio.Event) -> None:
        owner_token = "bobi-next-interaction-worker"
        while not stop_event.is_set():
            try:
                result = await process_next_interaction(
                    self.interaction_dispatches,
                    self.interaction_handlers,
                    self._transport_for,
                    owner_token=owner_token,
                    now_ts=int(time.time()),
                )
            except Exception as exc:
                # Do not log option content or user identifiers.
                logger.warning(
                    "Bobi Next interaction worker error type=%s",
                    type(exc).__name__,
                )
                await self._idle(stop_event)
                continue
            if result is None:
                await self._idle(stop_event)

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
        provider_running = any(not task.done() for task in self.tasks.values())
        interaction_running = (
            self.interaction_task is not None and not self.interaction_task.done()
        )
        if provider_running or interaction_running:
            return MessagingRuntimeStatus(True, "already_running", tuple(sorted(self.tasks)))
        status = self.prepare()
        if not status.ready:
            return status

        try:
            recovered = reconcile_poll_dispatches(
                self.interactions,
                self.interaction_dispatches,
                now_ts=int(time.time()),
            )
        except Exception as exc:
            logger.warning(
                "Bobi Next interaction recovery failed type=%s",
                type(exc).__name__,
            )
            return MessagingRuntimeStatus(
                False,
                f"interaction_recovery_failed:{type(exc).__name__}",
                status.providers,
            )
        if recovered:
            logger.info("Bobi Next recovered interaction dispatches count=%d", recovered)

        self.stop_event = asyncio.Event()
        self.tasks = {
            provider_key: asyncio.create_task(
                self._worker(provider_key, boundary, self.stop_event),
                name=f"bobi-next-messaging-{_provider_storage_key(provider_key)}",
            )
            for provider_key, boundary in self.boundaries.items()
        }
        self.interaction_task = asyncio.create_task(
            self._interaction_worker(self.stop_event),
            name="bobi-next-interactions",
        )
        return MessagingRuntimeStatus(True, "started", tuple(sorted(self.tasks)))

    async def aclose(self) -> None:
        if self._closed:
            return
        if self.stop_event is not None:
            self.stop_event.set()

        all_tasks = list(self.tasks.values())
        if self.interaction_task is not None:
            all_tasks.append(self.interaction_task)
        for task in all_tasks:
            if not task.done():
                task.cancel()
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self.tasks.clear()
        self.interaction_task = None
        self.stop_event = None

        for boundary in self.boundaries.values():
            boundary.messages.close()
        self.boundaries.clear()
        self.interaction_dispatches.close()
        self.interactions.close()
        self.ai_store.close()
        self.secrets.close()
        self.approvals.close()
        self.schedules.close()
        self.undo_requests.close()
        self.activity.close()
        self.requests.close()
        self.memory.close()
        self._closed = True
