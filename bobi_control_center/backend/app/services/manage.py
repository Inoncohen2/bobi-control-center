"""Preview, confirm, commit, verify.

This is where the five-step write flow is enforced, and it is enforced here so
that no route, adapter or screen can skip a step:

1. **Preview** validates the request and describes it in Hebrew. It computes
   only — no bridge call that changes anything is reachable from this path.
2. The preview is **stored, once**, with an expiry.
3. **Commit** requires that preview's id, an explicit confirmation, and — for a
   destructive change — the confirmation word the preview handed out. It then
   consumes the preview so the same confirmation cannot be replayed.
4. The write bridge applies the operation and is asked to **read it back**.
5. The result says which of the three things happened, without optimism.

Every preview and every commit writes an audit line, including the refusals.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.adapters.management import (
    UNAVAILABLE_MESSAGE,
    WRITES_DISABLED_MESSAGE,
    ManagementBridge,
)
from app.errors import BobiError, NotFoundError, ValidationError
from app.models.manage import (
    DESTRUCTIVE_OPERATIONS,
    FEATURE_OPERATIONS,
    TASK_OPERATIONS,
    AuditEntry,
    AuditLog,
    BridgeOutcome,
    ChangeField,
    CommitRequest,
    CommitResponse,
    ManagementStatus,
    ObservedState,
    PreviewRequest,
    PreviewResponse,
    ResourceSnapshot,
    TaskSnapshot,
    VerificationResult,
    WriteResult,
)
from app.models.manage import ValidationError as FieldError
from app.services.audit import AuditTrail
from app.services.describe import (
    allowed_private_fields,
    describe,
    find_item,
    observed_from,
)
from app.services.resource_normalize import unavailable
from app.services.resources import SPECS

logger = logging.getLogger("bobi.manage")

#: The families whose previews are generated from the bridge's own description.
#: `tasks` and `features` keep their Phase 3A describers untouched — they are
#: the two contracts Home Assistant has actually shipped, and rewriting a
#: working path to look like the new one would be a change with no upside.
GENERIC_RESOURCES = frozenset(SPECS) - {"tasks", "features"}

#: How long a preview stays valid. Long enough to read and confirm, short
#: enough that a forgotten dialog cannot commit an hour-old intention.
PREVIEW_TTL = timedelta(minutes=5)

#: The most audit lines kept in memory. The trail is for the current session,
#: not an archive — nothing here is persisted.
AUDIT_LIMIT = 200

#: Typed by the user to confirm a destructive change.
DESTRUCTIVE_CONFIRM_WORD = "מחק"

_MAX_TITLE = 200

#: Bridge refusal reasons worth explaining. Anything else falls through to the
#: plain "השינוי לא בוצע", which is still honest.
_REASON_MESSAGES = {
    "writes_disabled": WRITES_DISABLED_MESSAGE,
    "not_confirmed": "השינוי לא אושר",
    "duplicate": "כבר קיימת משימה פתוחה עם אותו תוכן.",
    "invalid_user": "המשתמש אינו מורשה לניהול משימות.",
    "invalid_summary": "תוכן המשימה אינו תקין.",
    "invalid_due_date": "תאריך היעד אינו בפורמט הנכון.",
    "not_found": "לא מצאנו את המשימה. ייתכן שהיא נמחקה.",
    "verification_failed": "הפעולה בוצעה אך הקריאה חזרה לא אישרה אותה.",
}


class ManagementUnavailableError(BobiError):
    """No Home Assistant write bridge has declared itself."""

    status_code = 503
    code = "management_unavailable"
    message = UNAVAILABLE_MESSAGE


class PreviewExpiredError(BobiError):
    """The preview is gone: expired, already used, or never existed."""

    status_code = 409
    code = "preview_expired"
    message = "התצוגה המקדימה כבר לא תקפה. אפשר לנסות שוב."


class WritesDisabledError(BobiError):
    """The bridge is there; Home Assistant's master write switch is off.

    A 409 rather than a 5xx, because nothing is broken. This is the expected
    state today, and the screen presents it as a disabled feature rather than a
    connection failure.
    """

    status_code = 409
    code = "writes_disabled"
    message = WRITES_DISABLED_MESSAGE


class StateChangedError(BobiError):
    """What the preview observed is no longer true, so nothing was done."""

    status_code = 409
    code = "stale_preview"
    message = "המצב השתנה מאז התצוגה המקדימה. אפשר לנסות שוב."


class ConfirmationRequiredError(BobiError):
    """A commit arrived without the user actually confirming."""

    status_code = 428
    code = "confirmation_required"
    message = "צריך לאשר את השינוי לפני ביצוע"


def _now() -> datetime:
    return datetime.now(UTC)


#: Field names that must never reach an audit line or a preview.
_PRIVATE_FIELDS = ("phone", "lid", "jid", "chat_id", "wa_id", "token", "secret", "number")


def sanitise(payload: dict[str, Any], keep: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Drop anything resembling a phone number, id or credential.

    Applied to everything that gets stored or echoed. Almost nothing on the
    management path needs such a field, so removing it costs nothing and closes
    the possibility of one leaking into the audit trail.

    `keep` is the one exception, and it is deliberately narrow: changing a
    household member's phone number cannot be done without the number, so
    `users.set_phone` names `phone` here and nothing else names anything. The
    audit line is sanitised again on the way out with no `keep` at all, so even
    that field reaches the trail masked rather than whole.
    """
    return {
        key: value
        for key, value in payload.items()
        if key in keep or not any(private in key.lower() for private in _PRIVATE_FIELDS)
    }


class _StoredPreview:
    """A preview waiting to be confirmed.

    Server-side only, single use, and bound to everything the commit will need:
    the operation, the resource, the requested values **and the state observed
    when the preview was taken**. The client gets an opaque id and nothing else,
    so it cannot alter what it is confirming — there is no payload on the commit
    request for it to alter.

    `token` is a *second* secret, minted at the same moment and never leaving
    this process except on the commit call to Home Assistant, which refuses a
    commit that does not carry one. It is deliberately not the `preview_id`:
    the id is handed to the browser, and a value the browser has seen is one
    that could be replayed straight at `script.bobi_cc_*` from Developer Tools.
    The token is the half that proves a commit came through this preview flow.
    """

    __slots__ = (
        "consumed",
        "expires_at",
        "observed",
        "operation",
        "payload",
        "resource_id",
        "resource_type",
        "response",
        "token",
    )

    def __init__(
        self,
        response: PreviewResponse,
        resource_type: str,
        payload: dict[str, Any],
        observed: ObservedState,
        expires_at: datetime,
        token: str,
    ) -> None:
        self.response = response
        self.resource_type = resource_type
        self.operation = response.operation
        self.resource_id = response.resource_id
        self.payload = payload
        self.observed = observed
        self.expires_at = expires_at
        self.token = token
        self.consumed = False


class ManagementService:
    """The write flow, independent of FastAPI and of any bridge."""

    def __init__(
        self, bridge: ManagementBridge | None, trail: AuditTrail | None = None
    ) -> None:
        self._bridge = bridge
        self._previews: dict[str, _StoredPreview] = {}
        self._audit: list[AuditEntry] = []
        # A memory-only trail keeps every call site identical when there is no
        # `/data` — a test, a laptop — rather than making every write check.
        self._trail = trail if trail is not None else AuditTrail(None)

    # --- discovery --------------------------------------------------------
    async def status(self) -> ManagementStatus:
        """What Home Assistant has declared. Unavailable is the default."""
        if self._bridge is None:
            return ManagementStatus(
                available=False, reason=UNAVAILABLE_MESSAGE, writes_enabled=False
            )
        status = await self._bridge.status()
        # `writes_enabled` is reported exactly as Home Assistant states it —
        # discovered, never assumed, and never settable from here. It is off
        # today, which is why commits are refused and previews are not.
        #
        # The three `requires_*` flags are not permission to skip a step: this
        # application previews, confirms and verifies whatever they say.
        return status.model_copy(
            update={
                "requires_preview": True,
                "requires_confirmation": True,
                "requires_read_after_write": True,
            }
        )

    async def snapshot(self) -> TaskSnapshot:
        """The task list a preview binds to. Read-only, and fails closed."""
        if self._bridge is None:
            raise ManagementUnavailableError()
        return await self._bridge.snapshot()

    async def resource_snapshot(self, resource: str) -> ResourceSnapshot:
        """One family's current state. Read-only, and it fails closed.

        No bridge at all answers "unavailable" rather than raising: a screen
        that can say *why* it is empty is more use than an error page, and this
        is the same answer a bridge that has not shipped yet produces.
        """
        if self._bridge is None:
            return unavailable(resource, UNAVAILABLE_MESSAGE)
        return await self._bridge.resource_snapshot(resource)

    async def _require_bridge(
        self, resource_type: str, operation: str, *, for_write: bool = False
    ) -> ManagementBridge:
        """Fail closed, and record the refusal.

        `for_write` adds the master-switch check. A preview deliberately does
        not need it: reading and describing a change is safe while writes are
        off, and it is how the flow gets tested end to end before the switch is
        ever flipped.
        """
        if self._bridge is None:
            self._record(
                stage="preview",
                operation=operation,
                resource_type=resource_type,
                resource_id=None,
                requested_change={},
                result="refused",
            )
            raise ManagementUnavailableError()

        status = await self.status()
        resource = next((r for r in status.resources if r.id == resource_type), None)
        if not status.available or resource is None or not resource.available:
            self._record(
                stage="preview",
                operation=operation,
                resource_type=resource_type,
                resource_id=None,
                requested_change={},
                result="refused",
            )
            raise ManagementUnavailableError(
                (resource.detail if resource else None) or UNAVAILABLE_MESSAGE
            )
        if resource.operations and operation not in {op.id for op in resource.operations}:
            raise ValidationError(
                "הפעולה הזו אינה נתמכת על ידי הגשר של בובי",
                details={"operation": operation, "resource": resource_type},
            )
        if for_write and not status.writes_enabled:
            # Home Assistant's master switch is off. Expected, not an error —
            # and nothing here may turn it on.
            self._record(
                stage="commit",
                operation=operation,
                resource_type=resource_type,
                resource_id=None,
                requested_change={},
                result="refused",
            )
            raise WritesDisabledError()
        return self._bridge

    # --- preview ----------------------------------------------------------
    async def preview(self, resource_type: str, request: PreviewRequest) -> PreviewResponse:
        """Describe the change. Performs no write of any kind."""
        bridge = await self._require_bridge(resource_type, request.operation)

        payload = sanitise(
            request.payload, keep=allowed_private_fields(resource_type, request.operation)
        )

        if resource_type in GENERIC_RESOURCES:
            return await self._preview_resource(bridge, resource_type, request, payload)

        # Read what the resource looks like *now*. Home Assistant compares
        # against this immediately before it acts, so it is the preview's job to
        # capture it — not the client's to supply it.
        observed = await bridge.observe(resource_type, request.resource_id)
        if observed is None:
            return _invalid(
                request.operation,
                request.resource_id,
                _heading(resource_type, request.operation),
                [
                    FieldError(
                        field=None,
                        code="state_unavailable",
                        message=(
                            "לא הצלחנו לקרוא את המצב הנוכחי מ-Home Assistant, "
                            "ולכן אי אפשר להציג תצוגה מקדימה."
                        ),
                    )
                ],
            ).model_copy(update={"resource_type": resource_type})

        if resource_type == "tasks":
            response = _preview_task(request.operation, request.resource_id, payload, observed)
        elif resource_type == "features":
            response = _preview_feature(request.operation, request.resource_id, payload, observed)
        else:  # pragma: no cover - the router restricts this first.
            raise NotFoundError("משאב לא מוכר")

        return self._store_preview(response, resource_type, request, payload, observed)

    async def _preview_resource(
        self,
        bridge: ManagementBridge,
        resource_type: str,
        request: PreviewRequest,
        payload: dict[str, Any],
    ) -> PreviewResponse:
        """A 3.0 family's preview, described from what the bridge published.

        The snapshot is read once and used for everything: to find the item, to
        learn its limits, to bind the observation the commit will carry, and —
        for users — to count the admins. One read, so the whole preview
        describes a single consistent moment rather than several.
        """
        snapshot = await bridge.resource_snapshot(resource_type)
        if not snapshot.available:
            return _invalid(
                request.operation,
                request.resource_id,
                SPECS[resource_type].label,
                [
                    FieldError(
                        field=None,
                        code="resource_unavailable",
                        message=snapshot.reason or UNAVAILABLE_MESSAGE,
                    )
                ],
            ).model_copy(update={"resource_type": resource_type})

        response = describe(
            resource_type, request.operation, request.resource_id, payload, snapshot
        )
        observed = observed_from(find_item(snapshot, request.resource_id))
        return self._store_preview(response, resource_type, request, payload, observed)

    def _store_preview(
        self,
        response: PreviewResponse,
        resource_type: str,
        request: PreviewRequest,
        payload: dict[str, Any],
        observed: ObservedState,
    ) -> PreviewResponse:
        """Stamp a described change with its ids, keep it, and record the line."""
        expires_at = _now() + PREVIEW_TTL
        preview_id = f"pv_{secrets.token_urlsafe(24)}"
        # Minted here, with the preview, and not at commit time: a token created
        # when the commit arrives would prove nothing about a preview having
        # happened, which is the one thing Home Assistant is asking it to prove.
        preview_token = f"pt_{secrets.token_urlsafe(32)}"
        response = response.model_copy(
            update={
                "preview_id": preview_id,
                "resource_type": resource_type,
                "expires_at": expires_at.isoformat(),
                "would_execute": False,
            }
        )

        if response.valid:
            self._previews[preview_id] = _StoredPreview(
                response, resource_type, payload, observed, expires_at, preview_token
            )

        self._record(
            stage="preview",
            operation=request.operation,
            resource_type=resource_type,
            resource_id=request.resource_id,
            requested_change=payload,
            result="previewed" if response.valid else "refused",
        )
        return response

    # --- commit -----------------------------------------------------------
    async def commit(self, resource_type: str, request: CommitRequest) -> CommitResponse:
        """Apply a previewed, confirmed change, then read it back."""
        stored = self._previews.get(request.preview_id)
        if stored is None or stored.consumed or stored.expires_at < _now():
            raise PreviewExpiredError()
        if stored.resource_type != resource_type:
            raise PreviewExpiredError()

        preview = stored.response
        # An echo that disagrees with what was previewed is a rejected commit,
        # never a silently corrected one.
        if request.operation is not None and request.operation != stored.operation:
            raise PreviewExpiredError()
        if request.resource_id is not None and request.resource_id != stored.resource_id:
            raise PreviewExpiredError()

        if not request.confirmed:
            raise ConfirmationRequiredError()
        if preview.destructive and request.confirm_word != preview.confirm_word:
            raise ConfirmationRequiredError(
                f'למחיקה יש להקליד "{preview.confirm_word}" כדי לאשר'
            )

        bridge = await self._require_bridge(
            resource_type, preview.operation, for_write=True
        )

        # Consume before applying: a failed commit must not leave a preview
        # that a retry could replay against changed state.
        stored.consumed = True

        request_id = f"req_{secrets.token_urlsafe(12)}"
        try:
            outcome = await bridge.apply(
                resource_type=resource_type,
                operation=preview.operation,
                resource_id=preview.resource_id,
                payload=stored.payload,
                observed=stored.observed,
                request_id=request_id,
                # The token this very preview was issued, never one made up
                # here — Home Assistant reads it as proof that a preview was
                # taken and confirmed before anything was asked of it.
                preview_token=stored.token,
            )
        except BobiError as exc:
            return self._failed(request, resource_type, preview, stored, exc.message, exc.code)

        return self._report(request, resource_type, preview, stored, outcome)

    def _report(
        self,
        request: CommitRequest,
        resource_type: str,
        preview: PreviewResponse,
        stored: _StoredPreview,
        outcome: BridgeOutcome,
    ) -> CommitResponse:
        """Turn the bridge's answer into one of three honest outcomes.

        The bridge does its own read-after-write, so `verified` is its word.
        A change that landed but could not be confirmed is neither a success nor
        a failure, which is why there are three states and not a boolean.
        """
        resource_id = outcome.resource_id or preview.resource_id

        # The world moved between the preview and the commit, and Home Assistant
        # refused rather than acting on a stale picture. Nothing happened.
        if outcome.reason == "stale_preview":
            return self._failed(
                request,
                resource_type,
                preview,
                stored,
                StateChangedError.message,
                "stale_preview",
            )

        if not outcome.executed and outcome.verified and outcome.reason == "already_in_state":
            # Nothing needed doing, and the bridge confirmed the desired state
            # holds. That is a verified success, said plainly.
            return self._respond(
                request,
                resource_type,
                preview,
                stored,
                WriteResult(
                    status="committed",
                    message="השינוי בוצע ואומת",
                    resource_id=resource_id,
                    reason=outcome.reason,
                    verification=VerificationResult(
                        verified=True,
                        method="read_after_write",
                        detail="המצב כבר היה כמבוקש — לא נדרש שינוי.",
                    ),
                ),
            )

        if not outcome.executed:
            return self._failed(
                request,
                resource_type,
                preview,
                stored,
                _REASON_MESSAGES.get(outcome.reason or ""),
                outcome.reason,
            )

        verified = bool(outcome.verified)
        return self._respond(
            request,
            resource_type,
            preview,
            stored,
            WriteResult(
                status="committed" if verified else "committed_unverified",
                message=("השינוי בוצע ואומת" if verified else "השינוי בוצע אך לא הצלחנו לאמת"),
                resource_id=resource_id,
                reason=outcome.reason,
                verification=VerificationResult(
                    verified=verified,
                    method="read_after_write",
                    detail=None if verified else "הפעולה בוצעה אך הקריאה חזרה לא אישרה אותה.",
                ),
            ),
        )

    def _failed(
        self,
        request: CommitRequest,
        resource_type: str,
        preview: PreviewResponse,
        stored: _StoredPreview,
        detail: str | None,
        reason: str | None,
    ) -> CommitResponse:
        return self._respond(
            request,
            resource_type,
            preview,
            stored,
            WriteResult(
                status="failed",
                message="השינוי לא בוצע",
                resource_id=preview.resource_id,
                reason=reason,
                verification=VerificationResult(verified=False, detail=detail),
            ),
        )

    def _respond(
        self,
        request: CommitRequest,
        resource_type: str,
        preview: PreviewResponse,
        stored: _StoredPreview,
        result: WriteResult,
    ) -> CommitResponse:
        audit = self._record(
            stage="commit",
            operation=preview.operation,
            resource_type=resource_type,
            resource_id=result.resource_id,
            requested_change=stored.payload,
            result=result.status,
            verified=result.verification.verified,
        )
        return CommitResponse(
            preview_id=request.preview_id,
            operation=preview.operation,
            resource_type=resource_type,
            result=result,
            audit=audit,
        )

    # --- audit ------------------------------------------------------------
    def _record(
        self,
        *,
        stage: str,
        operation: str,
        resource_type: str,
        resource_id: str | None,
        requested_change: dict[str, Any],
        result: str,
        verified: bool | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=f"au_{secrets.token_urlsafe(8)}",
            timestamp=_now().isoformat(),
            stage=stage,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            # Sanitised with no `keep`: the one field a commit may carry —
            # a household member's phone number — is dropped here even though
            # it was allowed through to the bridge. The trail records that a
            # number changed, never which number it became.
            requested_change=sanitise(requested_change),
            result=result,
            verified=verified,
            source="web",
        )
        self._audit.append(entry)
        del self._audit[:-AUDIT_LIMIT]
        self._trail.append(entry)
        return entry

    def audit(self, limit: int = 50) -> AuditLog:
        """Newest first, from disk when there is a disk, memory otherwise.

        The file is the fuller record — it survives a restart — so it is
        preferred, and the in-memory list is the fallback for an install whose
        `/data` cannot be written.
        """
        records = self._trail.read(limit)
        if not records:
            records = list(reversed(self._audit))[:limit]
        return AuditLog(count=len(records), records=records)


# --- per-resource previews --------------------------------------------------
def _text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _invalid(
    operation: str, resource_id: str | None, title: str, errors: list[FieldError]
) -> PreviewResponse:
    return PreviewResponse(
        preview_id="",
        operation=operation,
        resource_type="",
        resource_id=resource_id,
        title=title,
        valid=False,
        errors=errors,
        expires_at=_now().isoformat(),
    )


_TASK_TITLES = {
    "add": "הוספת משימה",
    "edit": "שינוי תוכן משימה",
    "complete": "סימון משימה כבוצעה",
    "reopen": "החזרת משימה לפעילה",
    "delete": "מחיקת משימה",
}

_FEATURE_TITLE = "שינוי תכונה"


def _heading(resource_type: str, operation: str) -> str:
    if resource_type == "tasks":
        return _TASK_TITLES.get(operation, "שינוי משימה")
    return _FEATURE_TITLE


#: `YYYY-MM-DD`, the only shape the bridge accepts beside an empty string.
_DUE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _preview_task(
    operation: str,
    resource_id: str | None,
    payload: dict[str, Any],
    observed: ObservedState,
) -> PreviewResponse:
    """Describe a task change, in the words the dialog shows.

    Every "before" comes from `observed` — what the bridge reported a moment
    ago — rather than from what the client sent, so the dialog cannot describe a
    change against a state that was never true.
    """
    if operation not in TASK_OPERATIONS:
        raise ValidationError("פעולה לא מוכרת על משימה", details={"operation": operation})

    heading = _TASK_TITLES[operation]
    summary = _text(payload, "summary")
    new_summary = _text(payload, "new_summary")
    due_date = _text(payload, "due_date")
    user_id = _text(payload, "user_id")
    owner = _text(payload, "owner") or observed.values.get("owner")

    current_summary = observed.values.get("summary")
    current_status = observed.values.get("status")

    errors: list[FieldError] = []
    if operation == "add":
        if not summary:
            errors.append(
                FieldError(field="summary", code="required", message="צריך למלא את תוכן המשימה")
            )
        if not user_id:
            errors.append(
                FieldError(field="user_id", code="required", message="צריך לבחור למי המשימה שייכת")
            )
        if due_date and not _DUE_DATE.match(due_date):
            errors.append(
                FieldError(
                    field="due_date",
                    code="invalid",
                    message="תאריך היעד צריך להיות בפורמט YYYY-MM-DD",
                )
            )
    else:
        if not resource_id:
            errors.append(
                FieldError(field="resource_id", code="required", message="לא נבחרה משימה")
            )
        if operation == "edit" and not new_summary:
            errors.append(
                FieldError(field="new_summary", code="required", message="צריך למלא את התוכן החדש")
            )
        # The bridge refuses these itself; saying so before the user confirms is
        # kinder than letting the commit come back with `stale_preview`.
        if operation == "complete" and current_status == "completed":
            errors.append(
                FieldError(field=None, code="already", message="המשימה כבר מסומנת כבוצעה")
            )
        if operation == "reopen" and current_status == "needs_action":
            errors.append(FieldError(field=None, code="already", message="המשימה כבר פתוחה"))

    for value, field in ((summary, "summary"), (new_summary, "new_summary")):
        if value and len(value) > _MAX_TITLE:
            errors.append(
                FieldError(
                    field=field,
                    code="too_long",
                    message=f"תוכן המשימה ארוך מדי (עד {_MAX_TITLE} תווים)",
                )
            )

    if errors:
        return _invalid(operation, resource_id, heading, errors)

    changes: list[ChangeField] = []
    if owner:
        changes.append(ChangeField(label="משתמש", before=owner, after=owner))

    if operation == "add":
        changes.append(ChangeField(label="משימה", before=None, after=summary))
        if due_date:
            changes.append(ChangeField(label="תאריך יעד", before=None, after=due_date))
        explanation = "המשימה תתווסף לרשימה של המשתמש."
    elif operation == "edit":
        changes.append(ChangeField(label="משימה", before=current_summary, after=new_summary))
        explanation = "תוכן המשימה יתעדכן. שאר הפרטים יישארו כפי שהם."
    elif operation == "complete":
        changes.append(ChangeField(label="משימה", before=current_summary, after=current_summary))
        changes.append(ChangeField(label="מצב", before="פתוחה", after="בוצעה"))
        explanation = "המשימה תסומן כבוצעה ותעבור לרשימת המשימות שהושלמו."
    elif operation == "reopen":
        changes.append(ChangeField(label="משימה", before=current_summary, after=current_summary))
        changes.append(ChangeField(label="מצב", before="בוצעה", after="פתוחה"))
        explanation = "המשימה תחזור לרשימת המשימות הפתוחות."
    else:  # delete
        changes.append(ChangeField(label="משימה", before=current_summary, after=None))
        explanation = "המשימה תוסר לגמרי מהרשימה."

    destructive = operation in DESTRUCTIVE_OPERATIONS
    return PreviewResponse(
        preview_id="",
        operation=operation,
        resource_type="",
        resource_id=resource_id,
        title=heading,
        changes=changes,
        explanation=explanation,
        destructive=destructive,
        warning=(
            "פעולה זו אינה הפיכה. המשימה תימחק ולא ניתן יהיה לשחזר אותה."
            if destructive
            else None
        ),
        confirm_word=DESTRUCTIVE_CONFIRM_WORD if destructive else None,
        confirm_label="מחק משימה" if destructive else "בצע שינוי",
        expires_at=_now().isoformat(),
    )


def _preview_feature(
    operation: str,
    resource_id: str | None,
    payload: dict[str, Any],
    observed: ObservedState,
) -> PreviewResponse:
    """Describe a feature toggle change.

    The current state comes from `observed` — the bridge's own reading. Home
    Assistant compares it again immediately before acting, so a preview that
    could not read it does not exist.
    """
    if operation not in FEATURE_OPERATIONS:
        raise ValidationError("פעולה לא מוכרת על תכונה", details={"operation": operation})

    label = observed.label or resource_id
    enabled = payload.get("enabled")
    current = observed.values.get("enabled")

    errors: list[FieldError] = []
    if not resource_id:
        errors.append(FieldError(field="resource_id", code="required", message="לא נבחרה תכונה"))
    if not isinstance(enabled, bool):
        errors.append(
            FieldError(field="enabled", code="required", message="צריך לבחור מצב חדש לתכונה")
        )
    if errors:
        return _invalid(operation, resource_id, _FEATURE_TITLE, errors)

    def state(value: Any) -> str:
        if value is True:
            return "פעילה"
        if value is False:
            return "כבויה"
        return "לא ידוע"

    heading = f"הפעלת {label}" if enabled else f"כיבוי {label}"
    return PreviewResponse(
        preview_id="",
        operation=operation,
        resource_type="",
        resource_id=resource_id,
        title=heading,
        changes=[
            ChangeField(label="תכונה", before=label, after=label),
            ChangeField(label="מצב", before=state(current), after=state(enabled)),
        ],
        explanation=(
            "בובי יתחיל להשתמש בתכונה הזו."
            if enabled
            else "בובי יפסיק להשתמש בתכונה הזו עד שתופעל מחדש."
        ),
        destructive=False,
        confirm_label="בצע שינוי",
        expires_at=_now().isoformat(),
    )
