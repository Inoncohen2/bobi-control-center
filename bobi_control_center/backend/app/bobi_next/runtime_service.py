"""Lifecycle composition for the opt-in Bobi Next runtime.

The service is intentionally dormant unless the application explicitly enables
it. When enabled it starts only after onboarding is complete, a Supervisor token
exists and an initial Home Assistant discovery succeeds. Messaging remains a
separate narrower gate and is shadow-only by default.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass

from app.config import Settings

from .archive_messaging_runtime import ArchiveMessagingRuntime
from .authorization import RiskLevel, UserPolicy
from .conditional import ConditionalRuleStore, StateChangeEvent
from .conditional_duration import ConditionalDurationRuntime, DurationCheckStore
from .conditional_runtime import ConditionalEventRuntime
from .event_reminders import EventReminderRuntime
from .ha_control import HomeAssistantNativeClient
from .ha_discovery import HomeAssistantDiscoveryClient
from .ha_events import HomeAssistantEventStream
from .live_catalog import LiveDeviceCatalog
from .pending_approval import PendingApprovalStore
from .setup_store import SetupStore

logger = logging.getLogger("bobi.next.runtime")


@dataclass(slots=True, frozen=True)
class RuntimeStartStatus:
    started: bool
    reason: str


def deny_all_policy(user_key: str) -> UserPolicy:
    return UserPolicy(
        user_key=user_key,
        allowed_capabilities=frozenset(),
        allowed_domains=frozenset(),
        max_without_approval=RiskLevel.LOW,
        can_approve=False,
    )


class BobiNextRuntimeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.setup = SetupStore(settings.data_dir / "bobi-next-setup.db")
        self.rules: ConditionalRuleStore | None = None
        self.duration_checks: DurationCheckStore | None = None
        self.duration_runtime: ConditionalDurationRuntime | None = None
        self.pending_approvals: PendingApprovalStore | None = None
        self.discovery: HomeAssistantDiscoveryClient | None = None
        self.native: HomeAssistantNativeClient | None = None
        self.catalog: LiveDeviceCatalog | None = None
        self.runtime: ConditionalEventRuntime | None = None
        self.messaging: ArchiveMessagingRuntime | None = None
        self.event_reminder_runtime: EventReminderRuntime | None = None
        self.stop_event: asyncio.Event | None = None
        self.task: asyncio.Task[None] | None = None
        self.duration_task: asyncio.Task[None] | None = None

    async def policy_for(self, user_key: str) -> UserPolicy:
        user = self.setup.get_user(user_key)
        if user is None or not user.enabled:
            return deny_all_policy(user_key)
        return user.policy

    def _user_enabled(self, user_key: str) -> bool:
        user = self.setup.get_user(user_key)
        return user is not None and user.enabled

    async def _handle_results(self, results) -> None:
        completed = sum(result.outcome == "completed" for result in results)
        approvals = sum(result.outcome == "approval_required" for result in results)
        failed = sum(result.outcome == "failed" for result in results)
        logger.info(
            "Bobi Next conditional event: completed=%s approval=%s failed=%s",
            completed,
            approvals,
            failed,
        )

    async def _observe_event_reminders(self, event: StateChangeEvent) -> None:
        runtime = self.event_reminder_runtime
        if runtime is None:
            return
        try:
            results = await runtime.observe_event(event)
        except Exception as exc:
            logger.warning(
                "Bobi Next event reminder observer failed closed: type=%s",
                type(exc).__name__,
            )
            return
        queued = sum(result.outcome == "queued" for result in results)
        if queued:
            logger.info("Bobi Next event reminders queued=%s", queued)

    async def _start_messaging_if_enabled(self) -> None:
        if not self.settings.next_messaging_enabled:
            return
        if self.native is None or self.catalog is None or self.pending_approvals is None:
            logger.warning("Bobi Next messaging not started: runtime_dependencies_missing")
            return

        runtime: ArchiveMessagingRuntime | None = None
        try:
            runtime = ArchiveMessagingRuntime(
                data_dir=self.settings.data_dir,
                setup=self.setup,
                ha=self.native,
                list_devices=self.catalog.get_devices,
                policy_for=self.policy_for,
                pending_approvals=self.pending_approvals,
                conditional_rules=self.rules,
                dry_run=self.settings.next_messaging_dry_run,
            )
            status = await runtime.start()
            if not status.ready:
                logger.warning(
                    "Bobi Next messaging not ready: reason=%s",
                    status.reason,
                )
                await runtime.aclose()
                return
            self.messaging = runtime
            self.event_reminder_runtime = EventReminderRuntime(
                definitions=runtime.event_reminders,
                reminders=runtime.reminders,
                list_devices=self.catalog.get_devices,
                user_enabled=self._user_enabled,
            )
            logger.info(
                "Bobi Next messaging started: providers=%s dry_run=%s",
                len(status.providers),
                self.settings.next_messaging_dry_run,
            )
        except Exception as exc:
            logger.warning(
                "Bobi Next messaging failed closed: type=%s",
                type(exc).__name__,
            )
            self.event_reminder_runtime = None
            if runtime is not None:
                with suppress(Exception):
                    await runtime.aclose()

    async def start_if_ready(self) -> RuntimeStartStatus:
        if self.task is not None and not self.task.done():
            return RuntimeStartStatus(True, "already_running")
        if not self.settings.has_supervisor_token:
            return RuntimeStartStatus(False, "missing_supervisor_token")

        setup_status = self.setup.status()
        if not setup_status.completed:
            return RuntimeStartStatus(False, "setup_not_completed")
        if not setup_status.ready:
            return RuntimeStartStatus(False, "setup_not_ready")

        token = self.settings.ha_token
        self.discovery = HomeAssistantDiscoveryClient(
            api_base_url=self.settings.ha_base_url,
            token=token,
            timeout_seconds=self.settings.ha_timeout_seconds,
        )
        self.native = HomeAssistantNativeClient(
            api_base_url=self.settings.ha_base_url,
            token=token,
            timeout_seconds=self.settings.ha_timeout_seconds,
        )
        self.catalog = LiveDeviceCatalog(self.discovery)
        try:
            await self.catalog.refresh()
        except Exception as exc:
            await self.discovery.aclose()
            await self.native.aclose()
            self.discovery = None
            self.native = None
            self.catalog = None
            logger.warning("Bobi Next initial discovery failed: %s", type(exc).__name__)
            return RuntimeStartStatus(False, "initial_discovery_failed")

        self.rules = ConditionalRuleStore(self.settings.data_dir / "bobi-next-conditionals.db")
        self.duration_checks = DurationCheckStore(
            self.settings.data_dir / "bobi-next-duration-checks.db"
        )
        self.pending_approvals = PendingApprovalStore(
            self.settings.data_dir / "bobi-next-pending-approvals.db"
        )
        self.duration_runtime = ConditionalDurationRuntime(
            checks=self.duration_checks,
            rules=self.rules,
            client=self.native,
            list_devices=self.catalog.get_devices,
            policy_for=self.policy_for,
            pending_approvals=self.pending_approvals,
            result_handler=self._handle_results,
        )

        async def observe_event(event: StateChangeEvent) -> None:
            if self.catalog is None or self.duration_runtime is None:
                return
            await self.catalog.apply_state_event(event)
            await self.duration_runtime.observe_event(event)
            await self._observe_event_reminders(event)

        stream = HomeAssistantEventStream(
            api_base_url=self.settings.ha_base_url,
            token=token,
            timeout_seconds=self.settings.ha_timeout_seconds,
        )
        self.runtime = ConditionalEventRuntime(
            stream=stream,
            store=self.rules,
            client=self.native,
            list_devices=self.catalog.get_devices,
            policy_for=self.policy_for,
            pending_approvals=self.pending_approvals,
            result_handler=self._handle_results,
            event_observer=observe_event,
        )
        self.stop_event = asyncio.Event()
        self.task = asyncio.create_task(
            self.runtime.run(stop_event=self.stop_event),
            name="bobi-next-conditional-runtime",
        )
        self.duration_task = asyncio.create_task(
            self.duration_runtime.run(
                stop_event=self.stop_event,
                owner_token="bobi-next-duration-worker",
            ),
            name="bobi-next-duration-runtime",
        )
        self.task.add_done_callback(self._runtime_done)
        self.duration_task.add_done_callback(self._runtime_done)
        await self._start_messaging_if_enabled()
        return RuntimeStartStatus(True, "started")

    @staticmethod
    def _runtime_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Bobi Next conditional runtime stopped: %s", type(exc).__name__)

    async def aclose(self) -> None:
        self.event_reminder_runtime = None

        if self.messaging is not None:
            with suppress(Exception):
                await self.messaging.aclose()
            self.messaging = None

        if self.stop_event is not None:
            self.stop_event.set()
        for task in (self.task, self.duration_task):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self.task = None
        self.duration_task = None
        self.stop_event = None

        if self.discovery is not None:
            await self.discovery.aclose()
        if self.native is not None:
            await self.native.aclose()
        self.discovery = None
        self.native = None
        self.catalog = None
        self.runtime = None
        self.duration_runtime = None

        if self.rules is not None:
            self.rules.close()
            self.rules = None
        if self.duration_checks is not None:
            self.duration_checks.close()
            self.duration_checks = None
        if self.pending_approvals is not None:
            self.pending_approvals.close()
            self.pending_approvals = None
        self.setup.close()
