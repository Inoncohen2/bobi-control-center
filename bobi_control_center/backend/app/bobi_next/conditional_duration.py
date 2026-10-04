"""Restart-safe duration conditions for Bobi Next.

A rule such as "if the door stays open for 30 seconds" must never fire from the
initial transition alone.  This module arms a durable deadline, cancels it when
the condition breaks, then re-reads the live Home Assistant state after the
deadline before handing execution back to the normal conditional runner.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .authorization import UserPolicy
from .conditional import (
    ConditionalRuleStore,
    StateChangeEvent,
    TriggerSpec,
    find_trigger_entity,
)
from .conditional_runner import ConditionalRunResult, _run_matched_rule
from .executor import HAControlClient
from .models import DeviceRecord
from .pending_approval import PendingApprovalStore

DeviceProvider = Callable[[], Awaitable[Iterable[DeviceRecord]]]
PolicyProvider = Callable[[str], Awaitable[UserPolicy]]
ResultHandler = Callable[[tuple[ConditionalRunResult, ...]], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class DurationCheck:
    rule_id: str
    source_event_id: str
    due_ts: int
    state: str
    owner_token: str = ""
    lease_until_ts: int = 0


class DurationCheckStore:
    """SQLite-backed duration deadlines with atomic leases."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conditional_duration_checks (
                rule_id TEXT PRIMARY KEY,
                source_event_id TEXT NOT NULL,
                due_ts INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                owner_token TEXT NOT NULL DEFAULT '',
                lease_until_ts INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_conditional_duration_due
                ON conditional_duration_checks(state, due_ts, lease_until_ts);
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> DurationCheck | None:
        if row is None:
            return None
        return DurationCheck(
            rule_id=str(row["rule_id"]),
            source_event_id=str(row["source_event_id"]),
            due_ts=int(row["due_ts"]),
            state=str(row["state"]),
            owner_token=str(row["owner_token"]),
            lease_until_ts=int(row["lease_until_ts"]),
        )

    def get(self, rule_id: str) -> DurationCheck | None:
        row = self._db.execute(
            "SELECT * FROM conditional_duration_checks WHERE rule_id=?",
            (rule_id,),
        ).fetchone()
        return self._row(row)

    def arm(
        self,
        *,
        rule_id: str,
        source_event_id: str,
        due_ts: int,
        now_ts: int,
    ) -> DurationCheck:
        """Arm once; later matching events do not reset an existing deadline."""

        if due_ts <= now_ts:
            due_ts = now_ts + 1
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                "SELECT state FROM conditional_duration_checks WHERE rule_id=?",
                (rule_id,),
            ).fetchone()
            if existing is None:
                self._db.execute(
                    """
                    INSERT INTO conditional_duration_checks(
                        rule_id,source_event_id,due_ts,state,created_ts,updated_ts
                    ) VALUES(?,?,?,'pending',?,?)
                    """,
                    (rule_id, source_event_id, due_ts, now_ts, now_ts),
                )
            elif str(existing["state"]) not in {"pending", "running"}:
                self._db.execute(
                    """
                    UPDATE conditional_duration_checks
                    SET source_event_id=?, due_ts=?, state='pending', owner_token='',
                        lease_until_ts=0, updated_ts=? WHERE rule_id=?
                    """,
                    (source_event_id, due_ts, now_ts, rule_id),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        result = self.get(rule_id)
        if result is None:
            raise RuntimeError("duration_check_not_persisted")
        return result

    def cancel(self, rule_id: str) -> None:
        with self._db:
            self._db.execute(
                "DELETE FROM conditional_duration_checks WHERE rule_id=?",
                (rule_id,),
            )

    def claim_due(
        self,
        *,
        owner_token: str,
        now_ts: int,
        lease_seconds: int = 60,
        limit: int = 20,
    ) -> tuple[DurationCheck, ...]:
        if not owner_token.strip():
            raise ValueError("owner_token_required")
        lease_until = now_ts + max(5, int(lease_seconds))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute(
                """
                SELECT rule_id FROM conditional_duration_checks
                WHERE due_ts <= ? AND (
                    state='pending' OR (state='running' AND lease_until_ts < ?)
                ) ORDER BY due_ts LIMIT ?
                """,
                (now_ts, now_ts, max(1, min(int(limit), 100))),
            ).fetchall()
            rule_ids = [str(row["rule_id"]) for row in rows]
            for rule_id in rule_ids:
                self._db.execute(
                    """
                    UPDATE conditional_duration_checks
                    SET state='running', owner_token=?, lease_until_ts=?, updated_ts=?
                    WHERE rule_id=?
                    """,
                    (owner_token, lease_until, now_ts, rule_id),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return tuple(
            check
            for rule_id in rule_ids
            if (check := self.get(rule_id)) is not None
            and check.owner_token == owner_token
        )

    def complete(self, rule_id: str, *, owner_token: str) -> None:
        check = self.get(rule_id)
        if check is None:
            return
        if check.state != "running" or check.owner_token != owner_token:
            raise PermissionError("duration_check_not_owned")
        self.cancel(rule_id)

    def release(
        self,
        rule_id: str,
        *,
        owner_token: str,
        retry_at_ts: int,
        now_ts: int,
    ) -> None:
        check = self.get(rule_id)
        if check is None:
            return
        if check.state != "running" or check.owner_token != owner_token:
            raise PermissionError("duration_check_not_owned")
        with self._db:
            self._db.execute(
                """
                UPDATE conditional_duration_checks
                SET state='pending', due_ts=?, owner_token='', lease_until_ts=0,
                    updated_ts=? WHERE rule_id=?
                """,
                (max(now_ts + 1, retry_at_ts), now_ts, rule_id),
            )


def condition_holds(
    trigger: TriggerSpec,
    *,
    state: Any,
    attributes: dict[str, Any],
) -> bool:
    """Evaluate the current value, not whether a transition just crossed it."""

    value = attributes.get(trigger.attribute) if trigger.attribute else state
    if trigger.kind == "state":
        if trigger.to_state is None:
            return False
        return str(value) == trigger.to_state

    if trigger.kind == "availability":
        unavailable = str(state) in {"unknown", "unavailable", "None"}
        if trigger.to_state == "available":
            return not unavailable
        if trigger.to_state == "unavailable":
            return unavailable
        return False

    if trigger.kind == "numeric":
        if value is None or isinstance(value, bool):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if trigger.above is not None and number <= trigger.above:
            return False
        if trigger.below is not None and number >= trigger.below:
            return False
        return trigger.above is not None or trigger.below is not None

    return False


class ConditionalDurationRuntime:
    def __init__(
        self,
        *,
        checks: DurationCheckStore,
        rules: ConditionalRuleStore,
        client: HAControlClient,
        list_devices: DeviceProvider,
        policy_for: PolicyProvider,
        pending_approvals: PendingApprovalStore | None = None,
        result_handler: ResultHandler | None = None,
        poll_seconds: float = 1.0,
        retry_seconds: int = 15,
        verification_attempts: int = 3,
        verification_delay: float = 0.35,
    ) -> None:
        self.checks = checks
        self.rules = rules
        self.client = client
        self.list_devices = list_devices
        self.policy_for = policy_for
        self.pending_approvals = pending_approvals
        self.result_handler = result_handler
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.retry_seconds = max(1, int(retry_seconds))
        self.verification_attempts = max(1, int(verification_attempts))
        self.verification_delay = max(0.0, float(verification_delay))

    async def observe_event(self, event: StateChangeEvent) -> None:
        devices = tuple(await self.list_devices())
        now = int(event.occurred_ts or time.time())
        for rule in self.rules.enabled_rules():
            trigger = rule.trigger
            if trigger.for_seconds <= 0:
                continue
            entity = find_trigger_entity(devices, stable_key=trigger.entity.stable_key)
            if entity is None or entity.entity_id != event.entity_id:
                continue
            if condition_holds(
                trigger,
                state=event.new_state,
                attributes=event.new_attributes,
            ):
                self.checks.arm(
                    rule_id=rule.rule_id,
                    source_event_id=event.event_id,
                    due_ts=now + trigger.for_seconds,
                    now_ts=now,
                )
            else:
                self.checks.cancel(rule.rule_id)

    async def run_due_once(
        self,
        *,
        owner_token: str,
        now_ts: int | None = None,
    ) -> tuple[ConditionalRunResult, ...]:
        now = int(now_ts or time.time())
        claimed = self.checks.claim_due(owner_token=owner_token, now_ts=now)
        if not claimed:
            return ()
        devices = tuple(await self.list_devices())
        results: list[ConditionalRunResult] = []
        for check in claimed:
            try:
                rule = self.rules.get(check.rule_id)
                if rule is None or not rule.enabled or rule.trigger.for_seconds <= 0:
                    self.checks.complete(check.rule_id, owner_token=owner_token)
                    continue
                entity = find_trigger_entity(
                    devices,
                    stable_key=rule.trigger.entity.stable_key,
                )
                if entity is None:
                    self.checks.release(
                        check.rule_id,
                        owner_token=owner_token,
                        retry_at_ts=now + self.retry_seconds,
                        now_ts=now,
                    )
                    continue
                snapshot = await self.client.get_state(entity.entity_id)
                if snapshot is None:
                    self.checks.release(
                        check.rule_id,
                        owner_token=owner_token,
                        retry_at_ts=now + self.retry_seconds,
                        now_ts=now,
                    )
                    continue
                state = snapshot.get("state")
                attrs_raw = snapshot.get("attributes")
                attributes = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}
                if not condition_holds(rule.trigger, state=state, attributes=attributes):
                    self.checks.complete(check.rule_id, owner_token=owner_token)
                    continue

                due_event = StateChangeEvent(
                    event_id=f"duration:{rule.rule_id}:{check.source_event_id}",
                    entity_id=entity.entity_id,
                    old_state=str(state) if state is not None else None,
                    new_state=str(state) if state is not None else None,
                    old_attributes=attributes,
                    new_attributes=attributes,
                    occurred_ts=now,
                )
                result = await _run_matched_rule(
                    self.rules,
                    rule,
                    due_event,
                    devices=devices,
                    client=self.client,
                    policy_for=self.policy_for,
                    pending_approvals=self.pending_approvals,
                    verification_attempts=self.verification_attempts,
                    verification_delay=self.verification_delay,
                )
                results.append(result)
                self.checks.complete(check.rule_id, owner_token=owner_token)
            except Exception:
                self.checks.release(
                    check.rule_id,
                    owner_token=owner_token,
                    retry_at_ts=now + self.retry_seconds,
                    now_ts=now,
                )

        completed = tuple(results)
        if completed and self.result_handler is not None:
            await self.result_handler(completed)
        return completed

    async def run(self, *, stop_event: asyncio.Event, owner_token: str) -> None:
        while not stop_event.is_set():
            await self.run_due_once(owner_token=owner_token)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                continue
