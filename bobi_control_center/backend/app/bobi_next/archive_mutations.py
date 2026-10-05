"""Deterministic private archive plans, approval continuation and verified execution.

This executor changes Bobi's semantic index only. Category changes and soft
deletion never move/delete immutable provider bytes or invoke an HA service.
The exact mutation and its receipt commit together, so crashes between execution
and messaging acknowledgement cannot apply a command to another search result.
"""

from __future__ import annotations

import hashlib
import uuid

from .archive_commands import archive_write_allowed
from .archive_mutation_commands import ArchiveMutationCommand
from .archive_store import ArchiveMutationReceipt, ArchiveRecord, ArchiveStore
from .authorization import (
    ApprovalStore,
    RequestProvenance,
    UserPolicy,
    authorize_plan,
    plan_fingerprint,
    state_fingerprint,
)
from .models import ActionPlan
from .pending_approval import PendingApproval, PendingApprovalStore
from .receipt_review import (
    display_financial_text,
    format_financial_fields,
    merge_review_fields,
    parse_receipt_review,
    reviewed_financial_fields,
)
from .request_ledger import RequestLedger


def archive_state_guard(record: ArchiveRecord) -> dict:
    return {
        "object_id": record.object_id,
        "owner_key": record.owner_key,
        "revision": record.revision,
        "status": record.status,
        "category": record.category,
        "sha256": record.sha256,
    }


def _chat_hash(chat_id: str) -> str:
    return hashlib.sha256(chat_id.encode()).hexdigest()


def _receipt_reply(receipt: ArchiveMutationReceipt) -> str:
    if receipt.operation == "move":
        return f"✅ העברתי את המסמך לתיקיית {receipt.record.category}."
    if receipt.operation == "delete":
        return "✅ המסמך הועבר לסל המחזור. אפשר לשחזר אותו."
    if receipt.operation == "review":
        return "✅ נשמרו פרטי המסמך שכתבת ואישרת. יתר הפרטים שחולצו עדיין דורשים בדיקה."
    return "✅ שחזרתי את המסמך לארכיון."


def _prompt(pending: PendingApproval) -> str:
    return f"{pending.summary} להשיב כן או לא."


class ArchiveMutationService:
    def __init__(
        self,
        archive: ArchiveStore,
        requests: RequestLedger,
        pending: PendingApprovalStore,
        approvals: ApprovalStore,
    ) -> None:
        self.archive = archive
        self.requests = requests
        self.pending = pending
        self.approvals = approvals

    def execute_command(
        self,
        command: ArchiveMutationCommand,
        *,
        request_id: str,
        user_key: str,
        provider: str,
        chat_id: str,
        input_text: str,
        policy: UserPolicy,
        now_ts: int,
        dry_run: bool = False,
    ) -> str:
        if not archive_write_allowed(policy, user_key=user_key, action=command.operation):
            return "אין הרשאה לשנות את המסמך בארכיון."
        if command.operation == "review" and parse_receipt_review(input_text) != command:
            return "נדרשים ערכים מפורשים בהודעה הנוכחית. פרטי המסמך לא שונו."
        if dry_run:
            return "הבקשה נבדקה במצב Shadow. הארכיון לא שונה."
        prior = self.requests.get(request_id)
        if prior and (prior.user_key != user_key or prior.input_text != input_text):
            return "הבקשה אינה תקפה. הארכיון לא שונה."
        owner_token = f"archive-mutation:{uuid.uuid4().hex}"
        claim = self.requests.claim(
            request_id=request_id,
            user_key=user_key,
            input_text=input_text,
            owner_token=owner_token,
            now_ts=now_ts,
        )
        if not claim.claimed:
            if claim.reason != "request_terminal":
                raise RuntimeError("archive_mutation_request_owned")
            receipt = self.archive.mutation_receipt(request_id, owner_key=user_key)
            if receipt:
                return _receipt_reply(receipt)
            if claim.record.terminal_kind == "archive_approval_required":
                pending = self.pending.get(self._approval_id(request_id))
                if (
                    pending
                    and pending.state in {"pending", "running"}
                    and pending.expires_ts >= now_ts
                ):
                    return _prompt(pending)
            return "הבקשה כבר טופלה. לא בוצע שינוי נוסף בארכיון."

        try:
            receipt = self.archive.mutation_receipt(request_id, owner_key=user_key)
            if receipt:
                text, terminal = _receipt_reply(receipt), "archive_mutated"
            else:
                text, terminal = self._prepare_command(
                    command,
                    request_id=request_id,
                    user_key=user_key,
                    provider=provider,
                    chat_id=chat_id,
                    policy=policy,
                    now_ts=now_ts,
                )
            self.requests.complete(
                request_id,
                owner_token=owner_token,
                terminal_kind=terminal,
                now_ts=now_ts,
            )
            return text
        except ValueError as exc:
            self.requests.fail_terminal(
                request_id,
                owner_token=owner_token,
                error=str(exc),
                now_ts=now_ts,
            )
            if str(exc) == "archive_review_currency_conflict":
                return (
                    "יש סכום שנבדק קודם במטבע אחר. כדי להחליף מטבע יש לציין מחדש "
                    "את הסכום ואת המע״מ שכבר נבדקו. לא בוצע שינוי."
                )
            return "מצב המסמך השתנה או שהבקשה אינה תקפה. לא בוצע שינוי."
        except BaseException:
            self.requests.retry(
                request_id,
                owner_token=owner_token,
                error="archive_mutation_interrupted",
                now_ts=now_ts,
            )
            raise

    @staticmethod
    def _approval_id(request_id: str) -> str:
        return "archive-ap:" + hashlib.sha256(request_id.encode()).hexdigest()

    def _prepare_command(
        self,
        command: ArchiveMutationCommand,
        *,
        request_id: str,
        user_key: str,
        provider: str,
        chat_id: str,
        policy: UserPolicy,
        now_ts: int,
    ) -> tuple[str, str]:
        existing = self.pending.get(self._approval_id(request_id))
        if existing is not None:
            if existing.user_key != user_key:
                raise ValueError("archive_approval_owner_mismatch")
            return _prompt(existing), "archive_approval_required"
        records = self.archive.search(
            owner_key=user_key,
            query=command.query,
            kind=command.kind,
            status="deleted" if command.operation == "restore" else "active",
            limit=6,
        )
        if not records:
            return "לא מצאתי מסמך שמתאים לבקשה הזאת.", "archive_not_found"
        if len(records) != 1:
            labels = " | ".join(
                f"{r.title} ({r.category})" if r.category else r.title for r in records[:5]
            )
            return (
                f"מצאתי כמה מסמכים מתאימים: {labels}. כתבו פרט נוסף לפני השינוי.",
                "clarification",
            )
        record = records[0]
        if command.operation == "review":
            if record.kind not in {"receipt", "bill"}:
                raise ValueError("archive_review_kind_invalid")
            merge_review_fields(
                reviewed_financial_fields(
                    record.metadata, owner_key=user_key, media_sha256=record.sha256,
                ),
                command.financial_fields,
            )
        guard = archive_state_guard(record)
        plan = ActionPlan(
            request_id=request_id,
            device_id=record.object_id,
            entity_id=f"archive:{record.object_id}",
            domain="archive",
            action=command.operation,
            capability="archive.write",
            data={
                "object_id": record.object_id,
                "owner_key": user_key,
                "category": command.category,
                "provider": provider,
                "chat_hash": _chat_hash(chat_id),
                **({"financial_fields": dict(command.financial_fields)}
                   if command.operation == "review" else {}),
            },
            expected=guard,
            requires_confirmation=command.operation in {"delete", "review"},
        )
        provenance = RequestProvenance(explicit_target_ids=frozenset({plan.entity_id}))
        decision = authorize_plan(plan, policy=policy, provenance=provenance)
        if decision.requires_approval:
            if not policy.can_approve:
                return "הפעולה דורשת אישור של משתמש מורשה.", "blocked"
            summary = (
                f'להעביר את המסמך "{record.title}" לסל המחזור?'
                if command.operation == "delete"
                else f'לאשר שינוי של המסמך "{record.title}"?'
            )
            if command.operation == "review":
                summary = (
                    f'לעדכן במסמך "{display_financial_text(record.title)}" את הפרטים שכתבת?\n'
                    + format_financial_fields(command.financial_fields)
                    + "\nרק השדות המפורשים האלה מתעדכנים. יתר החילוץ דורש בדיקה."
                )
            pending = self.pending.create(
                approval_request_id=self._approval_id(request_id),
                source_request_id=request_id,
                user_key=user_key,
                plans=(plan,),
                provenance=provenance,
                state_guards=(guard,),
                summary=summary,
                now_ts=now_ts,
            )
            return _prompt(pending), "archive_approval_required"
        if not decision.allowed:
            return "אין הרשאה לשנות את המסמך בארכיון.", "blocked"
        return _receipt_reply(
            self._execute(plan, user_key=user_key, now_ts=now_ts)
        ), "archive_mutated"

    def _execute(self, plan: ActionPlan, *, user_key: str, now_ts: int) -> ArchiveMutationReceipt:
        object_id = str(plan.data.get("object_id", ""))
        if (
            plan.domain != "archive"
            or plan.capability != "archive.write"
            or plan.action not in {"move", "delete", "restore", "review"}
            or plan.data.get("owner_key") != user_key
            or plan.device_id != object_id
            or plan.entity_id != f"archive:{object_id}"
            or plan.expected.get("owner_key") != user_key
            or plan.expected.get("object_id") != object_id
            or (plan.action == "review" and not plan.requires_confirmation)
        ):
            raise ValueError("archive_plan_invalid")
        return self.archive.apply_mutation_once(
            request_id=plan.request_id,
            owner_key=user_key,
            plan_hash=plan_fingerprint(plan),
            object_id=object_id,
            operation=plan.action,
            expected_revision=int(plan.expected["revision"]),
            category=str(plan.data.get("category", "")),
            financial_fields=plan.data.get("financial_fields"),
            now_ts=now_ts,
        )

    def continue_latest(
        self,
        *,
        confirmation_id: str,
        choice: str,
        user_key: str,
        provider: str,
        chat_id: str,
        policy: UserPolicy,
        now_ts: int,
        dry_run: bool = False,
    ) -> str | None:
        binding = self.archive.confirmation_binding(confirmation_id, owner_key=user_key)
        if binding:
            if binding[1] != choice:
                return "האישור אינו תקף. לא בוצעה פעולה."
            request_id = binding[0]
        else:
            latest = self.pending.peek_latest(user_key=user_key)
            if latest is None or not latest.plans or latest.plans[0].domain != "archive":
                return None
            request_id = latest.approval_request_id
            if dry_run:
                return "במצב Shadow לא מבוצעים שינויים בארכיון."
            if not self._same_channel(latest, provider, chat_id):
                return "האישור אינו שייך לשיחה הזאת. לא בוצעה פעולה."
            self.archive.bind_confirmation(
                confirmation_id,
                owner_key=user_key,
                approval_request_id=request_id,
                choice=choice,
            )
        return self.continue_exact(
            request_id,
            choice=choice,
            user_key=user_key,
            provider=provider,
            chat_id=chat_id,
            policy=policy,
            now_ts=now_ts,
            dry_run=dry_run,
        )

    @staticmethod
    def _same_channel(pending: PendingApproval, provider: str, chat_id: str) -> bool:
        return len(pending.plans) == 1 and (
            pending.plans[0].data.get("provider") == provider
            and pending.plans[0].data.get("chat_hash") == _chat_hash(chat_id)
        )

    def continue_exact(
        self,
        approval_request_id: str,
        *,
        choice: str,
        user_key: str,
        provider: str,
        chat_id: str,
        policy: UserPolicy,
        now_ts: int,
        dry_run: bool = False,
    ) -> str:
        if dry_run:
            return "במצב Shadow לא מבוצעים שינויים בארכיון."
        pending = self.pending.get(approval_request_id)
        if (
            choice not in {"approve", "reject"}
            or pending is None
            or pending.user_key != user_key
            or not self._same_channel(pending, provider, chat_id)
            or pending.plans[0].domain != "archive"
            or len(pending.state_guards) != 1
        ):
            return "האישור אינו תקף. לא בוצעה פעולה."
        plan = pending.plans[0]
        if pending.state == "completed":
            receipt = self.archive.mutation_receipt(plan.request_id, owner_key=user_key)
            return _receipt_reply(receipt) if receipt else "הבקשה כבר טופלה. לא בוצעה פעולה נוספת."
        owner_token = f"archive-approval:{uuid.uuid4().hex}"
        claimed = self.pending.claim(
            approval_request_id=approval_request_id,
            user_key=user_key,
            owner_token=owner_token,
            now_ts=now_ts,
        )
        if claimed is None:
            if pending.state == "running" and pending.lease_until_ts >= now_ts:
                raise RuntimeError("archive_approval_owned")
            return "האישור פג, בוטל או כבר טופל. לא בוצעה פעולה נוספת."
        if choice == "reject":
            self.pending.reject(approval_request_id, owner_token=owner_token, now_ts=now_ts)
            return "בוטל. הארכיון לא שונה."
        try:
            receipt = self.archive.mutation_receipt(plan.request_id, owner_key=user_key)
            if receipt is None:
                decision = authorize_plan(
                    plan,
                    policy=policy,
                    provenance=claimed.provenance,
                    approval_authorized=True,
                )
                if policy.user_key != user_key or not policy.can_approve or not decision.allowed:
                    raise ValueError("archive_approval_policy_denied")
                record = self.archive.get(plan.device_id, owner_key=user_key, include_deleted=True)
                if record is None or state_fingerprint(
                    archive_state_guard(record)
                ) != state_fingerprint(claimed.state_guards[0]):
                    raise ValueError("archive_approval_state_changed")
                grant = self.approvals.issue(
                    user_key=user_key,
                    plan=plan,
                    state_guard=archive_state_guard(record),
                    summary=claimed.summary,
                    now_ts=now_ts,
                )
                validation = self.approvals.consume(
                    token=grant.token,
                    user_key=user_key,
                    plan=plan,
                    state_guard=archive_state_guard(record),
                    now_ts=now_ts,
                )
                if not validation.valid:
                    raise ValueError("archive_approval_invalid")
                receipt = self._execute(plan, user_key=user_key, now_ts=now_ts)
            elif receipt.plan_hash != plan_fingerprint(plan):
                raise ValueError("archive_approval_plan_changed")
            self.pending.complete(approval_request_id, owner_token=owner_token, now_ts=now_ts)
            return _receipt_reply(receipt)
        except ValueError as exc:
            self.pending.fail(
                approval_request_id,
                owner_token=owner_token,
                error=str(exc),
                now_ts=now_ts,
            )
            return "מצב המסמך או ההרשאות השתנו. לא בוצע שינוי נוסף בארכיון."
        except BaseException:
            self.pending.release(
                approval_request_id,
                owner_token=owner_token,
                error="archive_approval_interrupted",
                now_ts=now_ts,
            )
            raise
