"""Runtime bridge from HA state events into Bobi Next conditional execution.

This object owns no policy and performs no direct service call.  It wires the
read-only Home Assistant event stream to the existing conditional runner, which
re-discovers devices and re-enters authorization + secure execution for every
matched rule.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from .authorization import UserPolicy
from .conditional import ConditionalRuleStore, StateChangeEvent
from .conditional_runner import ConditionalRunResult, run_conditional_event
from .executor import HAControlClient
from .ha_events import HomeAssistantEventStream
from .models import DeviceRecord
from .pending_approval import PendingApprovalStore

logger = logging.getLogger("bobi.next.conditional-runtime")

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]
ResultHandler = Callable[[tuple[ConditionalRunResult, ...]], Awaitable[None]]


@dataclass(slots=True)
class ConditionalRuntimeStats:
    events_seen: int = 0
    events_with_results: int = 0
    rules_completed: int = 0
    approvals_requested: int = 0
    rules_failed: int = 0


class ConditionalEventRuntime:
    def __init__(
        self,
        *,
        stream: HomeAssistantEventStream,
        store: ConditionalRuleStore,
        client: HAControlClient,
        list_devices: DeviceProvider,
        policy_for: PolicyProvider,
        pending_approvals: PendingApprovalStore | None = None,
        result_handler: ResultHandler | None = None,
        verification_attempts: int = 3,
        verification_delay: float = 0.35,
    ) -> None:
        self.stream = stream
        self.store = store
        self.client = client
        self.list_devices = list_devices
        self.policy_for = policy_for
        self.pending_approvals = pending_approvals
        self.result_handler = result_handler
        self.verification_attempts = max(1, int(verification_attempts))
        self.verification_delay = max(0.0, float(verification_delay))
        self.stats = ConditionalRuntimeStats()

    async def handle_event(
        self,
        event: StateChangeEvent,
    ) -> tuple[ConditionalRunResult, ...]:
        self.stats.events_seen += 1
        results = await run_conditional_event(
            self.store,
            self.client,
            event=event,
            list_devices=self.list_devices,
            policy_for=self.policy_for,
            pending_approvals=self.pending_approvals,
            verification_attempts=self.verification_attempts,
            verification_delay=self.verification_delay,
        )
        if results:
            self.stats.events_with_results += 1
        for result in results:
            if result.outcome == "completed":
                self.stats.rules_completed += 1
            elif result.outcome == "approval_required":
                self.stats.approvals_requested += 1
            elif result.outcome == "failed":
                self.stats.rules_failed += 1
        if self.result_handler is not None and results:
            await self.result_handler(results)
        return results

    async def run(self, *, stop_event: asyncio.Event) -> None:
        """Run until stopped; reconnect policy belongs to the HA event stream."""

        await self.stream.run_forever(self.handle_event, stop_event=stop_event)
