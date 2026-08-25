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
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.adapters.management import UNAVAILABLE_MESSAGE, ManagementBridge
from app.errors import BobiError, NotFoundError, ValidationError
from app.models.manage import (
    DESTRUCTIVE_OPERATIONS,
    FEATURE_OPERATIONS,
    TASK_OPERATIONS,
    AuditEntry,
    AuditLog,
    ChangeField,
    CommitRequest,
    CommitResponse,
    ManagementStatus,
    PreviewRequest,
    PreviewResponse,
    VerificationResult,
    WriteResult,
)
from app.models.manage import ValidationError as FieldError

logger = logging.getLogger("bobi.manage")

#: How long a preview stays valid. Long enough to read and confirm, short
#: enough that a forgotten dialog cannot commit an hour-old intention.
PREVIEW_TTL = timedelta(minutes=5)

#: The most audit lines kept in memory. The trail is for the current session,
#: not an archive — nothing here is persisted.
AUDIT_LIMIT = 200

#: Typed by the user to confirm a destructive change.
DESTRUCTIVE_CONFIRM_WORD = "מחק"

_MAX_TITLE = 200


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


class ConfirmationRequiredError(BobiError):
    """A commit arrived without the user actually confirming."""

    status_code = 428
    code = "confirmation_required"
    message = "צריך לאשר את השינוי לפני ביצוע"


def _now() -> datetime:
    return datetime.now(UTC)


#: Field names that must never reach an audit line or a preview.
_PRIVATE_FIELDS = ("phone", "lid", "jid", "chat_id", "wa_id", "token", "secret", "number")


def sanitise(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop anything resembling a phone number, id or credential.

    Applied to everything that gets stored or echoed. The management path never
    needs such a field, so removing it costs nothing and closes the possibility
    of one leaking into the audit trail.
    """
    return {
        key: value
        for key, value in payload.items()
        if not any(private in key.lower() for private in _PRIVATE_FIELDS)
    }


class _StoredPreview:
    """A preview waiting to be confirmed. Single use."""

    __slots__ = ("consumed", "expires_at", "payload", "resource_type", "response")

    def __init__(
        self,
        response: PreviewResponse,
        resource_type: str,
        payload: dict[str, Any],
        expires_at: datetime,
    ) -> None:
        self.response = response
        self.resource_type = resource_type
        self.payload = payload
        self.expires_at = expires_at
        self.consumed = False


class ManagementService:
    """The write flow, independent of FastAPI and of any bridge."""

    def __init__(self, bridge: ManagementBridge | None) -> None:
        self._bridge = bridge
        self._previews: dict[str, _StoredPreview] = {}
        self._audit: list[AuditEntry] = []

    # --- discovery --------------------------------------------------------
    async def status(self) -> ManagementStatus:
        """What Home Assistant has declared. Unavailable is the default."""
        if self._bridge is None:
            return ManagementStatus(
                available=False, reason=UNAVAILABLE_MESSAGE, writes_enabled=False
            )
        status = await self._bridge.status()
        # The Phase 2 invariant is the app's to state, not the bridge's: a
        # bridge claiming writes_enabled cannot turn unrestricted writes on.
        return status.model_copy(update={"writes_enabled": False})

    async def _require_bridge(self, resource_type: str, operation: str) -> ManagementBridge:
        """Fail closed, and record the refusal."""
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
        return self._bridge

    # --- preview ----------------------------------------------------------
    async def preview(self, resource_type: str, request: PreviewRequest) -> PreviewResponse:
        """Describe the change. Performs no write of any kind."""
        await self._require_bridge(resource_type, request.operation)

        payload = sanitise(request.payload)
        if resource_type == "tasks":
            response = _preview_task(request.operation, request.resource_id, payload)
        elif resource_type == "features":
            response = _preview_feature(request.operation, request.resource_id, payload)
        else:  # pragma: no cover - the router restricts this first.
            raise NotFoundError("משאב לא מוכר")

        expires_at = _now() + PREVIEW_TTL
        preview_id = f"pv_{secrets.token_urlsafe(16)}"
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
                response, resource_type, payload, expires_at
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
        if not request.confirmed:
            raise ConfirmationRequiredError()
        if preview.destructive and request.confirm_word != preview.confirm_word:
            raise ConfirmationRequiredError(
                f'למחיקה יש להקליד "{preview.confirm_word}" כדי לאשר'
            )

        bridge = await self._require_bridge(resource_type, preview.operation)

        # Consume before applying: a failed commit must not leave a preview
        # that a retry could replay against changed state.
        stored.consumed = True

        try:
            resource_id = await bridge.apply(
                resource_type=resource_type,
                operation=preview.operation,
                resource_id=preview.resource_id,
                payload=stored.payload,
            )
        except BobiError as exc:
            result = WriteResult(
                status="failed",
                message="השינוי לא בוצע",
                resource_id=preview.resource_id,
                verification=VerificationResult(verified=False, detail=exc.message),
            )
            audit = self._record(
                stage="commit",
                operation=preview.operation,
                resource_type=resource_type,
                resource_id=preview.resource_id,
                requested_change=stored.payload,
                result="failed",
                verified=False,
            )
            return CommitResponse(
                preview_id=request.preview_id,
                operation=preview.operation,
                resource_type=resource_type,
                result=result,
                audit=audit,
            )

        verification = await self._verify(
            bridge,
            resource_type=resource_type,
            operation=preview.operation,
            resource_id=resource_id or preview.resource_id,
            payload=stored.payload,
        )

        status = "committed" if verification.verified else "committed_unverified"
        result = WriteResult(
            status=status,
            message=(
                "השינוי בוצע ואומת"
                if verification.verified
                else "השינוי בוצע אך לא הצלחנו לאמת"
            ),
            resource_id=resource_id or preview.resource_id,
            verification=verification,
        )
        audit = self._record(
            stage="commit",
            operation=preview.operation,
            resource_type=resource_type,
            resource_id=result.resource_id,
            requested_change=stored.payload,
            result=status,
            verified=verification.verified,
        )
        return CommitResponse(
            preview_id=request.preview_id,
            operation=preview.operation,
            resource_type=resource_type,
            result=result,
            audit=audit,
        )

    async def _verify(
        self,
        bridge: ManagementBridge,
        *,
        resource_type: str,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> VerificationResult:
        """Read back, and treat any failure to confirm as unverified.

        A verification that itself errors must not be reported as success, and
        must not turn a change that did land into a "failed" — hence the third
        state.
        """
        try:
            return await bridge.verify(
                resource_type=resource_type,
                operation=operation,
                resource_id=resource_id,
                payload=payload,
            )
        except BobiError as exc:
            return VerificationResult(verified=False, method="read_after_write", detail=exc.message)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Read-after-write verification failed unexpectedly.")
            return VerificationResult(
                verified=False,
                method="read_after_write",
                detail="לא הצלחנו לקרוא את הערך בחזרה",
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
            requested_change=sanitise(requested_change),
            result=result,
            verified=verified,
            source="web",
        )
        self._audit.append(entry)
        del self._audit[:-AUDIT_LIMIT]
        return entry

    def audit(self, limit: int = 50) -> AuditLog:
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
    "create": "הוספת משימה",
    "rename": "שינוי שם משימה",
    "complete": "סימון משימה כבוצעה",
    "reopen": "החזרת משימה לפעילה",
    "delete": "מחיקת משימה",
}


def _preview_task(
    operation: str, resource_id: str | None, payload: dict[str, Any]
) -> PreviewResponse:
    """Describe a task change, in the words the dialog shows."""
    if operation not in TASK_OPERATIONS:
        raise ValidationError(
            "פעולה לא מוכרת על משימה", details={"operation": operation}
        )

    heading = _TASK_TITLES[operation]
    owner = _text(payload, "owner")
    title = _text(payload, "title")
    current_title = _text(payload, "current_title")

    errors: list[FieldError] = []
    if operation in {"create", "rename"} and not title:
        errors.append(
            FieldError(field="title", code="required", message="צריך למלא את תוכן המשימה")
        )
    if title and len(title) > _MAX_TITLE:
        errors.append(
            FieldError(
                field="title",
                code="too_long",
                message=f"תוכן המשימה ארוך מדי (עד {_MAX_TITLE} תווים)",
            )
        )
    if operation == "create" and not owner:
        errors.append(
            FieldError(field="owner", code="required", message="צריך לבחור למי המשימה שייכת")
        )
    if operation != "create" and not resource_id:
        errors.append(
            FieldError(field="resource_id", code="required", message="לא נבחרה משימה")
        )
    if errors:
        return _invalid(operation, resource_id, heading, errors)

    changes: list[ChangeField] = []
    if owner:
        changes.append(ChangeField(label="משתמש", before=owner, after=owner))

    if operation == "create":
        changes.append(ChangeField(label="משימה", before=None, after=title))
        explanation = "המשימה תתווסף לרשימה של המשתמש."
    elif operation == "rename":
        changes.append(ChangeField(label="משימה", before=current_title, after=title))
        explanation = "תוכן המשימה יתעדכן. שאר הפרטים יישארו כפי שהם."
    elif operation == "complete":
        changes.append(ChangeField(label="משימה", before=current_title, after=current_title))
        changes.append(ChangeField(label="מצב", before="פתוחה", after="בוצעה"))
        explanation = "המשימה תסומן כבוצעה ותעבור לרשימת המשימות שהושלמו."
    elif operation == "reopen":
        changes.append(ChangeField(label="משימה", before=current_title, after=current_title))
        changes.append(ChangeField(label="מצב", before="בוצעה", after="פתוחה"))
        explanation = "המשימה תחזור לרשימת המשימות הפתוחות."
    else:  # delete
        changes.append(ChangeField(label="משימה", before=current_title, after=None))
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
    operation: str, resource_id: str | None, payload: dict[str, Any]
) -> PreviewResponse:
    """Describe a feature toggle change."""
    if operation not in FEATURE_OPERATIONS:
        raise ValidationError(
            "פעולה לא מוכרת על תכונה", details={"operation": operation}
        )

    label = _text(payload, "label") or resource_id
    enabled = payload.get("enabled")
    current = payload.get("current")

    errors: list[FieldError] = []
    if not resource_id:
        errors.append(FieldError(field="resource_id", code="required", message="לא נבחרה תכונה"))
    if not isinstance(enabled, bool):
        errors.append(
            FieldError(field="enabled", code="required", message="צריך לבחור מצב חדש לתכונה")
        )
    if errors:
        return _invalid(operation, resource_id, "שינוי תכונה", errors)

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
