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
from collections.abc import Awaitable, Callable

from .archive_retrieval import ArchiveRetrievalResult
from .archive_retrieval_commands import parse_archive_retrieval
from .archive_subsystem import ArchiveSubsystem
from .conversation_handler import build_conversation_handler
from .integration_runtime import build_archive_storage
from .media_analyzers import MediaAnalyzerRegistry
from .media_pipeline import MediaPipeline
from .messaging import InboundMessage, MessageResponse, MessageStore
from .messaging_runtime import (
    BobiNextMessagingRuntime,
    MessagingRuntimeStatus,
    ProviderBoundary,
)
from .presence_bindings import PresenceAwareEventReminderStore
from .reminders import ReminderStore, process_next_reminder
from .setup_store import MessagingProvider
from .understanding import ResilientUnderstandingProvider
from .waha_adapter import WahaMediaLoader, WahaTransport
from .waha_outbound_media import WahaOutboundMediaTransport

logger = logging.getLogger("bobi.next.archive-messaging")


def _provider_storage_key(provider_key: str) -> str:
    return hashlib.sha256(provider_key.encode()).hexdigest()[:20]


def _retrieval_reply(result: ArchiveRetrievalResult) -> str:
    if result.outcome == "prepared":
        return "📎 מצאתי. שולח את הקובץ עכשיו."
    if result.outcome == "blocked":
        return "אין הרשאה לשלוח מסמכים מהארכיון."
    if result.outcome == "not_found":
        return "לא מצאתי מסמך שמותאם לבקשה הזאת."
    if result.outcome == "unavailable":
        return "מצאתי את הרשומה, אבל הקובץ עצמו לא זמין כרגע."
    if result.outcome == "clarification":
        labels = []
        for candidate in result.candidates[:5]:
            label = candidate.title
            if candidate.category:
                label = f"{label} ({candidate.category})"
            labels.append(label)
        choices = " | ".join(labels)
        if choices:
            return f"מצאתי כמה מסמכים מתאימים: {choices}. כתבו פרט נוסף כדי שאדע איזה לשלוח."
        return "מצאתי כמה מסמכים מתאימים. כתבו פרט נוסף כדי שאדע איזה לשלוח."
    return "לא הצלחתי להכין את המסמך לשליחה בצורה בטוחה."


class ArchiveMessagingRuntime(BobiNextMessagingRuntime):
    """Messaging runtime with archive capture, delivery and proactive reminders."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.archive = ArchiveSubsystem(
            self.data_dir,
            storage=build_archive_storage(self.data_dir),
        )
        self.reminders = ReminderStore(self.data_dir / "bobi-next-reminders.db")
        self.event_reminders = PresenceAwareEventReminderStore(
            self.data_dir / "bobi-next-event-reminders.db",
            presence_path=self.data_dir / "bobi-next-presence.db",
        )
        self.archive_tasks: dict[str, asyncio.Task[None]] = {}
        self.reminder_task: asyncio.Task[None] | None = None

    def _archive_retrieval_handler(
        self,
        provider_key: str,
        base_handler: Callable[[InboundMessage], Awaitable[MessageResponse]],
    ) -> Callable[[InboundMessage], Awaitable[MessageResponse]]:
        retrieval = self.archive.retrieval(provider_key)

        async def handler(message: InboundMessage) -> MessageResponse:
            if message.kind == "text":
                command = parse_archive_retrieval(message.text)
                if command is not None:
                    now = int(message.received_ts or time.time())
                    policy = await self.policy_for(message.user_key)
                    result = retrieval.prepare_search(
                        owner_key=message.user_key,
                        policy=policy,
                        provider=provider_key,
                        chat_id=message.chat_id,
                        request_id=f"archive:{provider_key}:{message.message_id}",
                        query=command.query,
                        kind=command.kind,
                        reply_to=message.message_id,
                        now_ts=now,
                    )
                    text = _retrieval_reply(result)
                    self.memory.store_turn(
                        message.user_key,
                        message.text,
                        direction="inbound",
                        message_id=message.message_id,
                        created_ts=now,
                    )
                    self.memory.store_turn(
                        message.user_key,
                        text,
                        direction="outbound",
                        message_id=f"reply:{message.message_id}",
                        created_ts=now,
                    )
                    return MessageResponse(text)
            return await base_handler(message)

        return handler

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
        base_handler = build_conversation_handler(
            understanding=understanding,
            list_devices=self.list_devices,
            policy_for=self.policy_for,
            ha=self.ha,
            memory=self.memory,
            requests=self.requests,
            pending_approvals=self.pending_approvals,
            approval_tokens=self.approvals,
            schedules=self.schedules,
            reminders=self.reminders,
            event_reminders=self.event_reminders,
            conditional_rules=self.conditional_rules,
            media_pipeline=media_pipeline,
            archive_capture=self.archive.capture,
            activity=self.activity,
            undo_requests=self.undo_requests,
            dry_run=self.dry_run,
        )
        handler = self._archive_retrieval_handler(provider.provider_key, base_handler)
        return ProviderBoundary(provider, messages, transport, handler)

    def _reminder_user_enabled(self, user_key: str) -> bool:
        user = self.setup.get_user(user_key)
        return user is not None and user.enabled

    async def _reminder_worker(self, stop_event: asyncio.Event) -> None:
        owner_token = "bobi-next-reminder-worker"
        while not stop_event.is_set():
            try:
                result = await process_next_reminder(
                    self.reminders,
                    self._transport_for,
                    owner_token=owner_token,
                    now_ts=int(time.time()),
                    user_enabled=self._reminder_user_enabled,
                )
            except Exception as exc:
                logger.warning(
                    "Bobi Next reminder worker error type=%s",
                    type(exc).__name__,
                )
                await self._idle(stop_event)
                continue
            if result is None:
                await self._idle(stop_event)

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

        # Shadow mode must never emit proactive reminders. Reminder creation is
        # also dry-run in the engine, so no live reminder row is produced there.
        if not self.dry_run and (
            self.reminder_task is None or self.reminder_task.done()
        ):
            self.reminder_task = asyncio.create_task(
                self._reminder_worker(self.stop_event),
                name="bobi-next-reminder-worker",
            )
        return status

    async def aclose(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()

        reminder_task = self.reminder_task
        if reminder_task is not None and not reminder_task.done():
            reminder_task.cancel()
        if reminder_task is not None:
            await asyncio.gather(reminder_task, return_exceptions=True)
        self.reminder_task = None

        tasks = list(self.archive_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.archive_tasks.clear()

        await super().aclose()
        self.event_reminders.close()
        self.reminders.close()
        self.archive.close()
