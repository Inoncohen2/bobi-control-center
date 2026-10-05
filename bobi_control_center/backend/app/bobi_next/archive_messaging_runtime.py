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

from .archive_commands import archive_write_allowed
from .archive_mutation_commands import parse_archive_mutation
from .archive_mutations import ArchiveMutationService
from .archive_retrieval import ArchiveRetrievalResult, archive_read_allowed
from .archive_retrieval_commands import parse_archive_retrieval
from .archive_subsystem import ArchiveSubsystem
from .conversation_handler import (
    _NEGATIVE_APPROVALS,
    _POSITIVE_APPROVALS,
    _normalize_confirmation,
    build_conversation_handler,
)
from .event_reminders import EventReminderStore
from .expense_commands import (
    expense_allowed,
    expense_help,
    expense_requested,
    parse_expense_month,
    parse_expense_record,
)
from .expense_ledger import ALREADY_RECORDED, EXPENSE_RECORDED, ExpenseLedger
from .integration_runtime import RoutedArchiveStorage
from .interaction_dispatch import InteractionHandlerResult
from .media_analyzers import MediaAnalyzerRegistry
from .media_pipeline import MediaPipeline
from .messaging import InboundMessage, MessageResponse, MessageStore, OutboundMessage
from .messaging_runtime import (
    BobiNextMessagingRuntime,
    MessagingRuntimeStatus,
    ProviderBoundary,
)
from .receipt_review import (
    display_financial_text,
    parse_receipt_details,
    parse_receipt_review,
    receipt_details_reply,
    receipt_review_help,
    receipt_review_requested,
)
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
            storage=RoutedArchiveStorage(self.data_dir),
        )
        self.expenses = ExpenseLedger(self.archive.index.path)
        self.reminders = ReminderStore(self.data_dir / "bobi-next-reminders.db")
        self.event_reminders = EventReminderStore(self.data_dir / "bobi-next-event-reminders.db")
        self.archive_tasks: dict[str, asyncio.Task[None]] = {}
        self.reminder_task: asyncio.Task[None] | None = None
        self.archive_mutations = ArchiveMutationService(
            self.archive.index,
            self.requests,
            self.pending_approvals,
            self.approvals,
            self.expenses,
        )
        previous_approval_handler = self.interaction_handlers.get("approval")

        async def approval_handler(selection):
            namespace, _, request_id = selection.context_key.partition(":")
            pending = self.pending_approvals.get(request_id) if namespace == "approval" else None
            if pending and pending.plans and pending.plans[0].domain in {"archive", "expenses"}:
                if len(selection.selected_keys) != 1:
                    return InteractionHandlerResult(
                        "invalid_selection", "יש לבחור אפשרות אחת בלבד."
                    )
                policy = await self.policy_for(selection.user_key)
                text = self.archive_mutations.continue_exact(
                    request_id,
                    choice=selection.selected_keys[0],
                    user_key=selection.user_key,
                    provider=selection.provider,
                    chat_id=selection.chat_id,
                    policy=policy,
                    now_ts=int(time.time()),
                    dry_run=self.dry_run,
                )
                return InteractionHandlerResult("archive_approval_handled", text)
            if previous_approval_handler:
                return await previous_approval_handler(selection)
            return InteractionHandlerResult("invalid_approval", "האישור אינו תקף. לא בוצעה פעולה.")

        self.register_interaction_handler("approval", approval_handler)

    def _archive_retrieval_handler(
        self,
        provider_key: str,
        base_handler: Callable[[InboundMessage], Awaitable[MessageResponse]],
    ) -> Callable[[InboundMessage], Awaitable[MessageResponse]]:
        retrieval = self.archive.retrieval(provider_key)

        async def handler(message: InboundMessage) -> MessageResponse:
            if message.kind == "text":
                review = parse_receipt_review(message.text)
                expense = parse_expense_record(message.text)
                mutation = expense or review or parse_archive_mutation(message.text)
                normalized = _normalize_confirmation(message.text)
                now = int(time.time())
                mutation_text = None
                if expense is None and expense_requested(message.text):
                    mutation_text = expense_help()
                elif review is None and receipt_review_requested(message.text):
                    mutation_text = receipt_review_help()
                elif mutation is not None:
                    policy = await self.policy_for(message.user_key)
                    mutation_text = self.archive_mutations.execute_command(
                        mutation,
                        request_id=f"archive-mutate:{message.provider}:{message.message_id}",
                        user_key=message.user_key,
                        provider=message.provider,
                        chat_id=message.chat_id,
                        input_text=message.text,
                        policy=policy,
                        now_ts=now,
                        dry_run=self.dry_run,
                    )
                elif normalized in _POSITIVE_APPROVALS | _NEGATIVE_APPROVALS:
                    policy = await self.policy_for(message.user_key)
                    mutation_text = self.archive_mutations.continue_latest(
                        confirmation_id=f"archive-confirm:{message.provider}:{message.message_id}",
                        choice="approve" if normalized in _POSITIVE_APPROVALS else "reject",
                        user_key=message.user_key,
                        provider=message.provider,
                        chat_id=message.chat_id,
                        policy=policy,
                        now_ts=now,
                        dry_run=self.dry_run,
                    )
                if mutation_text is not None:
                    return self._remember_archive_reply(message, mutation_text, now_ts=now)
                expense_month = parse_expense_month(message.text)
                if expense_month is not None:
                    policy = await self.policy_for(message.user_key)
                    text = self.expenses.month_reply(
                        owner_key=message.user_key, month=expense_month,
                    ) if expense_allowed(
                        policy, user_key=message.user_key, action="summary",
                    ) else "אין הרשאה לקרוא את יומן ההוצאות."
                    return self._remember_archive_reply(message, text, now_ts=now)
                details = parse_receipt_details(message.text)
                if details is not None:
                    policy = await self.policy_for(message.user_key)
                    if not archive_read_allowed(
                        policy, user_key=message.user_key, action="details",
                    ):
                        text = "אין הרשאה לקרוא את פרטי המסמך בארכיון."
                    else:
                        records = self.archive.index.search(
                            owner_key=message.user_key, query=details.query,
                            kind=details.kind, limit=6,
                        )
                        if not records:
                            text = "לא מצאתי מסמך שמתאים לבקשה הזאת."
                        elif len(records) != 1:
                            titles = " | ".join(
                                display_financial_text(record.title) for record in records[:5]
                            )
                            text = f"מצאתי כמה מסמכים מתאימים: {titles}. כתבו פרט נוסף."
                        else:
                            text = receipt_details_reply(records[0])
                    return self._remember_archive_reply(message, text, now_ts=now)
                command = parse_archive_retrieval(message.text)
                if command is not None:
                    if self.dry_run:
                        return MessageResponse("במצב Shadow לא נשלחים קבצים מהארכיון.")
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
                    return self._remember_archive_reply(message, text, now_ts=now)
            return await base_handler(message)

        return handler

    def _remember_archive_reply(
        self, message: InboundMessage, text: str, *, now_ts: int,
    ) -> MessageResponse:
        self.memory.store_turn(
            message.user_key, message.text, direction="inbound",
            message_id=message.message_id, created_ts=now_ts,
        )
        self.memory.store_turn(
            message.user_key, text, direction="outbound",
            message_id=f"reply:{message.message_id}", created_ts=now_ts,
        )
        return MessageResponse(text)

    async def _private_financial_reply_allowed(
        self, message: InboundMessage, outbound: OutboundMessage,
    ) -> bool:
        """Reauthorize fresh/cached financial replies without regenerating their payload."""
        details = parse_receipt_details(message.text) if message.kind == "text" else None
        review = parse_receipt_review(message.text) if message.kind == "text" else None
        expense = parse_expense_record(message.text) if message.kind == "text" else None
        expense_month = parse_expense_month(message.text) if message.kind == "text" else None
        if details is None and review is None and expense is None and expense_month is None:
            return True
        if outbound.text in {
            "אין הרשאה לקרוא את פרטי המסמך בארכיון.",
            "אין הרשאה לשנות את המסמך בארכיון.",
            "הפעולה דורשת אישור של משתמש מורשה.",
            "לא מצאתי מסמך שמתאים לבקשה הזאת.",
            "הבקשה נבדקה במצב Shadow. הארכיון לא שונה.",
            "✅ נשמרו פרטי המסמך שכתבת ואישרת. יתר הפרטים שחולצו עדיין דורשים בדיקה.",
            "אין הרשאה לרשום הוצאה מהקבלה.",
            "אין הרשאה לקרוא את יומן ההוצאות.",
            "הבקשה נבדקה במצב Shadow. לא נרשמה הוצאה.",
            ALREADY_RECORDED,
            EXPENSE_RECORDED,
        }:
            return True
        actor = message.metadata.get("sender_fingerprint")
        if isinstance(actor, str) and actor:
            if message.metadata.get("sender_fingerprint_scope") != message.provider:
                return False
            user = self.setup.resolve_user_fingerprint(message.provider, actor)
        elif message.chat_id.endswith("@g.us"):
            # Older group inboxes lack a trustworthy participant binding.
            return False
        else:
            user = self.setup.resolve_user(message.provider, message.chat_id)
        if user is None or user.user_key != message.user_key:
            return False
        policy = await self.policy_for(message.user_key)
        if expense_month is not None:
            return expense_allowed(policy, user_key=message.user_key, action="summary")
        if expense is not None:
            return expense_allowed(
                policy, user_key=message.user_key, action="record",
            ) and archive_read_allowed(
                policy, user_key=message.user_key, action="details",
            ) and policy.can_approve
        if details is not None:
            return archive_read_allowed(policy, user_key=message.user_key, action="details")
        return archive_write_allowed(
            policy, user_key=message.user_key, action="review",
        ) and policy.can_approve

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
            self.data_dir / f"bobi-next-messages-{_provider_storage_key(provider.provider_key)}.db"
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
        return ProviderBoundary(
            provider, messages, transport, handler,
            reply_allowed=self._private_financial_reply_allowed,
        )

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
        if self.dry_run:
            return
        transport = boundary.transport
        if not isinstance(transport, WahaTransport):
            return
        outbound = WahaOutboundMediaTransport(
            base_url=transport.base_url,
            session=transport.session,
            api_key=transport.api_key,
        )
        owner_token = f"bobi-next-archive-media:{provider_key}"

        async def read_allowed(dispatch):
            policy = await self.policy_for(dispatch.owner_key)
            return archive_read_allowed(policy, user_key=dispatch.owner_key)

        while not stop_event.is_set():
            try:
                result = await self.archive.process_next(
                    provider_key,
                    outbound,
                    owner_token=owner_token,
                    now_ts=int(time.time()),
                    dispatch_allowed=read_allowed,
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
        if not status.ready or self.stop_event is None or self.dry_run:
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
        if not self.dry_run and (self.reminder_task is None or self.reminder_task.done()):
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
        self.expenses.close()
        self.archive.close()
