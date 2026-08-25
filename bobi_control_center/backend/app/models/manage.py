"""The management contract — Phase 3A.

Every change to Bobi goes through the same five steps, and this module is where
that shape lives:

    edit → **preview** → explicit confirmation → **commit** → verify → result

A preview computes and describes; it never writes. A commit refuses to run
without the id of a preview the user actually saw and confirmed, and reports
what it did only after reading the value back.

Two rules hold across every model here:

* **Fail closed.** Management is unavailable until a Home Assistant write
  bridge declares itself. Absent means refused, never "try anyway".
* **Nothing optimistic.** `WriteResult` distinguishes *committed and verified*
  from *committed but unverified*. The UI must not show a saved state until the
  read-back agrees.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.bridge import CanonicalModel

#: Resources Phase 3A prepares. Anything else is refused by the router, so a
#: later milestone has to add itself here deliberately.
MANAGED_RESOURCES = ("tasks", "features")

#: Operations, per resource. `reopen` is listed because a task list may support
#: it; the bridge decides, and an unsupported operation is simply not offered.
TASK_OPERATIONS = ("create", "rename", "complete", "reopen", "delete")
FEATURE_OPERATIONS = ("set",)

#: Operations that destroy something a person cannot get back by undoing.
DESTRUCTIVE_OPERATIONS = frozenset({"delete"})


class ValidationError(CanonicalModel):
    """One reason a request cannot proceed, in words a household member reads."""

    #: The input this concerns, if any — `title`, `owner`, …
    field: str | None = None
    code: str
    #: Hebrew.
    message: str


class ChangeField(CanonicalModel):
    """One before/after row of a preview.

    `before` is `None` for something being created, `after` for something being
    removed. Both are already rendered as text: the preview is what a person
    reads, not a diff of internal values.
    """

    label: str
    before: str | None = None
    after: str | None = None


class PreviewRequest(BaseModel):
    """What the user is asking to change.

    `extra="forbid"`: an unrecognised key here would be a silent instruction to
    the write bridge, so it is rejected rather than ignored.
    """

    model_config = ConfigDict(extra="forbid")

    operation: str
    #: The thing being changed — a task id, a feature id. Absent when creating.
    resource_id: str | None = None
    #: Operation-specific fields, validated per operation.
    payload: dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(CanonicalModel):
    """What will happen, described — and nothing done.

    `would_execute` is hard-coded `False` for the same reason the probe's is:
    it states an invariant rather than reporting one.
    """

    preview_id: str
    operation: str
    resource_type: str
    resource_id: str | None = None

    #: Hebrew heading, e.g. "הוספת משימה".
    title: str
    #: The before/after rows the dialog lists.
    changes: list[ChangeField] = Field(default_factory=list)
    #: One sentence of plain explanation.
    explanation: str | None = None

    #: Deleting needs more than an OK button.
    destructive: bool = False
    #: Hebrew, shown only for a destructive change.
    warning: str | None = None
    #: The word the user must type to confirm a destructive change.
    confirm_word: str | None = None
    #: Hebrew label for the confirm button, e.g. "מחק משימה".
    confirm_label: str = "אישור"

    valid: bool = True
    errors: list[ValidationError] = Field(default_factory=list)

    #: ISO-8601. A preview goes stale so a stale confirmation cannot commit.
    expires_at: str
    #: A preview never writes. Stated, not derived.
    would_execute: bool = False


class CommitRequest(BaseModel):
    """The confirmation of a preview the user has seen."""

    model_config = ConfigDict(extra="forbid")

    preview_id: str
    #: The user pressed the confirm button. A commit without it is refused.
    confirmed: bool = False
    #: For a destructive change: the word from `PreviewResponse.confirm_word`,
    #: typed by the user.
    confirm_word: str | None = None


class VerificationResult(CanonicalModel):
    """Whether reading the resource back agreed with what was asked for."""

    verified: bool = False
    #: How it was checked — `read_after_write` today.
    method: str | None = None
    #: Hebrew, when verification did not agree or could not run.
    detail: str | None = None


class WriteResult(CanonicalModel):
    """The honest outcome of a commit.

    Three states, never collapsed into a boolean: a change that happened but
    could not be confirmed is not a success, and it is not a failure either.
    """

    #: `committed` · `committed_unverified` · `failed`.
    status: str
    #: Hebrew, exactly what the screen shows.
    message: str
    resource_id: str | None = None
    verification: VerificationResult = Field(default_factory=VerificationResult)


class AuditEntry(CanonicalModel):
    """One line of the trail, for previews and commits alike.

    Carries no secret, no phone number and no LID: the payload is sanitised
    before it gets here.
    """

    id: str
    #: ISO-8601, UTC.
    timestamp: str
    #: `preview` or `commit`.
    stage: str
    operation: str
    resource_type: str
    resource_id: str | None = None
    requested_change: dict[str, Any] = Field(default_factory=dict)
    #: `previewed` · `committed` · `committed_unverified` · `failed` · `refused`.
    result: str
    verified: bool | None = None
    #: Where the request came from. Only the web UI exists today.
    source: str = "web"


class CommitResponse(CanonicalModel):
    """The result of a commit, with the audit line it produced."""

    preview_id: str
    operation: str
    resource_type: str
    result: WriteResult
    audit: AuditEntry


class ManagedOperation(CanonicalModel):
    """One operation the write bridge says it supports."""

    id: str
    label: str
    destructive: bool = False


class ManagementResource(CanonicalModel):
    """What can be managed, and how."""

    id: str
    label: str
    available: bool = False
    operations: list[ManagedOperation] = Field(default_factory=list)
    #: Hebrew, when unavailable — why not.
    detail: str | None = None


class ManagementStatus(CanonicalModel):
    """Whether Home Assistant has declared a write bridge at all.

    Discovered from the bridge, never from configuration: there is deliberately
    no setting or environment variable that can turn management on.
    """

    available: bool = False
    #: Hebrew. The screen shows this when management is off.
    reason: str | None = None
    #: The HA-side contract's own version, once it declares one.
    contract_version: str | None = None
    resources: list[ManagementResource] = Field(default_factory=list)
    #: The Phase 2 invariant, still false: unrestricted writes remain off.
    writes_enabled: bool = False


class AuditLog(CanonicalModel):
    """Recent management activity, newest first."""

    count: int = 0
    records: list[AuditEntry] = Field(default_factory=list)
