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

#: Every family the router will accept in a URL. Anything else is refused
#: before a service is consulted, so a resource cannot be managed by guessing
#: its name — a new one has to be added here deliberately, with a spec in
#: `app.services.resources` and a describer to match.
#:
#: Being listed here is *permission to ask*, not availability: the management
#: contract decides whether Home Assistant actually offers the family, and a
#: family it does not name stays unavailable however complete this list is.
MANAGED_RESOURCES = (
    "tasks",
    "features",
    "lists",
    "vouchers",
    "settings",
    "users",
    "shabbat",
    "rules",
    "calendar",
    "devices",
    "helpers",
    "automations",
    "scripts",
    "scenes",
    "system",
)

#: Operations, per resource — named exactly as the Home Assistant contract
#: names them, so nothing has to be translated on the way out. The bridge
#: declares which of these it supports; anything it omits is never offered.
TASK_OPERATIONS = ("add", "edit", "complete", "reopen", "delete")
FEATURE_OPERATIONS = ("set",)

#: Operations that destroy something a person cannot get back by undoing.
DESTRUCTIVE_OPERATIONS = frozenset({"delete"})


class ObservedState(CanonicalModel):
    """What the resource looked like when the preview was taken.

    This is the other half of the safety story: Home Assistant re-checks these
    values immediately before it acts, and refuses with `stale_preview` if the
    world moved on. So a preview binds to what it saw, and the commit carries
    that forward unchanged.
    """

    resource_id: str | None = None
    #: A readable name for the preview dialog.
    label: str | None = None
    #: The exact values the bridge will compare against — `summary`, `status`,
    #: `state`. Never anything the user typed.
    values: dict[str, Any] = Field(default_factory=dict)


class BridgeOutcome(CanonicalModel):
    """What the Home Assistant write bridge reported.

    The bridge performs its own read-after-write, so `verified` is its answer,
    not a guess made here. `reason` is its own token — `stale_preview`,
    `already_in_state`, and whatever else it may add.
    """

    executed: bool = False
    verified: bool | None = None
    reason: str | None = None
    resource_id: str | None = None
    #: The bridge's master switch, as it reported it on this call.
    writes_enabled: bool = False


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

    #: `read_only` · `low` · `medium` · `high` · `destructive`. The screen
    #: escalates its confirmation with it, and the role check reads the same
    #: value — so what a person is warned about and what they are allowed to do
    #: can never drift apart.
    risk: str = "low"

    valid: bool = True
    errors: list[ValidationError] = Field(default_factory=list)

    #: ISO-8601. A preview goes stale so a stale confirmation cannot commit.
    expires_at: str
    #: A preview never writes. Stated, not derived.
    would_execute: bool = False


class CommitRequest(BaseModel):
    """The confirmation of a preview the user has seen.

    Deliberately carries no payload. Everything that will be sent to Home
    Assistant comes from the stored preview, so a client cannot alter what it
    confirmed. `operation` and `resource_id` may be echoed back, and are then
    checked against the stored preview — a mismatch is a rejected commit, not a
    silently corrected one.
    """

    model_config = ConfigDict(extra="forbid")

    preview_id: str
    #: The user pressed the confirm button. A commit without it is refused.
    confirmed: bool = False
    #: For a destructive change: the word from `PreviewResponse.confirm_word`,
    #: typed by the user.
    confirm_word: str | None = None
    #: Optional echoes, checked for agreement with the stored preview.
    operation: str | None = None
    resource_id: str | None = None


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
    #: The bridge's own reason token, kept for the technical view.
    reason: str | None = None
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
    #: Where the request came from — `ingress` or `external`.
    source: str = "web"
    #: The authority the change was made under: a role and a route, never a
    #: name or an address. "Who was allowed to do this" is the question the
    #: trail exists to answer; "who exactly" is not one it should hold.
    actor: str | None = None


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
    #: This verb takes no payload — running it is the whole request, so a screen
    #: may offer it as a single button. One that needs a value may not. Defaults
    #: to false so a verb nobody has classified is treated as needing one.
    valueless: bool = False


class ManagedTarget(CanonicalModel):
    """Something an operation may be applied to.

    For tasks these are the household members the bridge will accept; for
    features, the feature ids it will accept. Either way the id is the bridge's
    own token — never a Home Assistant entity id, which the bridge does not
    hand out and this app must not reconstruct.
    """

    id: str
    label: str
    #: Features only, when the bridge rates them.
    risk: str | None = None
    #: Features only: current state, when the bridge reports it. `None` means
    #: unknown, which blocks a preview rather than being guessed.
    enabled: bool | None = None


class ManagementResource(CanonicalModel):
    """What can be managed, and how."""

    id: str
    label: str
    available: bool = False
    operations: list[ManagedOperation] = Field(default_factory=list)
    #: Who or what the operations may target.
    targets: list[ManagedTarget] = Field(default_factory=list)
    #: Hebrew, when unavailable — why not.
    detail: str | None = None


class ManagementStatus(CanonicalModel):
    """Whether Home Assistant has declared a write bridge at all.

    Discovered from the bridge, never from configuration: there is deliberately
    no setting or environment variable that can turn management on.
    """

    #: The bridge answered and declares itself usable. Previews may run.
    available: bool = False
    #: Hebrew. The screen shows this when management is off.
    reason: str | None = None
    #: The HA-side contract's own version.
    contract_version: str | None = None
    resources: list[ManagementResource] = Field(default_factory=list)

    #: Home Assistant's live master write switch, **as the bridge reports it**.
    #: When it is off previews still work and commits are refused. Nothing in
    #: this application can turn it on, and no endpoint tries.
    writes_enabled: bool = False
    #: The flow the bridge requires. All three are true today, and this app does
    #: all three regardless — it never relaxes a step because the bridge said it
    #: could.
    requires_preview: bool = True
    requires_confirmation: bool = True
    requires_read_after_write: bool = True


class SnapshotTask(CanonicalModel):
    """One task as the management snapshot reports it.

    `uid` is the bridge's own task id — the handle a commit needs. No Home
    Assistant `todo.*` entity id appears here, because the bridge does not send
    one and this app must not infer one.
    """

    uid: str
    summary: str
    status: str
    completed: bool = False
    due: str | None = None
    owner_id: str
    owner: str


class TaskSnapshot(CanonicalModel):
    """Normalized `script.bobi_cc_task_snapshot` — open and completed alike."""

    count: int = 0
    tasks: list[SnapshotTask] = Field(default_factory=list)
    owners: list[ManagedTarget] = Field(default_factory=list)
    writes_enabled: bool = False


class AuditLog(CanonicalModel):
    """Recent management activity, newest first."""

    count: int = 0
    records: list[AuditEntry] = Field(default_factory=list)


# --- the contract-driven resources (3.0) ------------------------------------
# Phase 3A hard-coded two families because the bridge published exactly two.
# The families below are described by the bridge instead: it names the items, it
# says which are operable, and it supplies the limits. Nothing here decides what
# Bobi can do — it decides only how to *say* it in Hebrew, and how to refuse.


class ManagedOption(CanonicalModel):
    """One allowed value of a choice, as the bridge offered it."""

    value: str
    label: str
    #: Hebrew, when picking this option deserves a word of warning.
    detail: str | None = None


class ManagedConstraints(CanonicalModel):
    """The limits the bridge published for one item.

    Every one is optional, and an absent limit is never invented: an item with
    no `minimum` is not thereby unbounded, it is an item whose bound this
    application does not know. Home Assistant checks its own limits again.
    """

    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    #: `°`, `דק׳`, `%` — appended when a value is shown.
    unit: str | None = None
    max_length: int | None = None
    #: For a list item: the tokens it may hold, e.g. Shabbat profile membership.
    allowed: list[ManagedOption] = Field(default_factory=list)


#: How an item is edited. The UI renders from this and from `constraints`;
#: an unrecognised kind is shown read-only rather than guessed at.
#:
#: `action` is the one that holds no value. A self-check has nothing to set and
#: nothing to read back — it is a thing you run — and every other kind here
#: assumes an item *is* a value, so the system bridge's two safe checks arrived
#: `controllable: true` and rendered as readings. Forcing them into a toggle
#: would have been worse than the bug: a toggle says it can be switched back.
ITEM_KINDS = (
    "toggle", "number", "time", "date", "datetime", "choice", "text", "list", "action", "readonly"
)

#: Kinds an item may be operated without reporting a current value. Everywhere
#: else a missing value means the bridge could not read the item, and an item
#: whose value is unknown must not be written — a preview binds to what was
#: observed, and there is nothing to bind to.
VALUELESS_KINDS = frozenset({"action"})


class ManagedItem(CanonicalModel):
    """One thing a person can look at, and sometimes change.

    A setting, a notification class, a user, a Shabbat profile field, a rule, a
    calendar event, a device control, a system action. The shape is deliberately
    the same for all of them: the bridge describes, this application renders.
    """

    id: str
    label: str
    #: Which card it belongs under — `morning`, `shabbat_alert`, `salon`.
    group: str | None = None
    kind: str = "readonly"
    #: The canonical current value. `None` means the bridge did not report one,
    #: which makes the item unoperable rather than assumed.
    value: Any = None
    #: Hebrew rendering of `value`, for screens that only display.
    display: str | None = None
    description: str | None = None
    #: `read_only` · `low` · `medium` · `high` · `destructive`.
    risk: str = "read_only"
    #: Whether a write UI may be shown at all. False unless the bridge says so.
    controllable: bool = False
    #: The operations the bridge accepts for this item, from the closed set.
    operations: list[str] = Field(default_factory=list)
    #: Which of those operations sets the value this item reports.
    #:
    #: An item publishes one value and, under the live vocabulary, several
    #: verbs — an air conditioner accepts `power`, `temperature`, `fan_mode`
    #: and `swing_mode` while reporting a temperature. Nothing in the payload
    #: says which verb produces the reported value, and a screen taking the
    #: first name in the list would send `power` for a temperature edit.
    #:
    #: So it is decided once, here, rather than guessed by every component that
    #: draws a control. `None` means there is nothing to operate.
    primary_operation: str | None = None
    #: The verbs on this item that are a whole request on their own, and that
    #: no control drawn for `kind` already sends.
    #:
    #: `primary_operation` answers "what does the editor send"; this answers
    #: "what is left over". They are different questions and the second one was
    #: not being asked: a scene arrived with `activate` named on it and no value
    #: to edit, so nothing was drawn at all, and an automation's switch covered
    #: `enable`/`disable` while "run it now" quietly went nowhere.
    #:
    #: Decided here for the same reason as `primary_operation` — the rule needs
    #: to know that a toggle's switch stands for `enable`, `disable`, `set`,
    #: `power`, `start` and `stop` at once, and that is this module's knowledge,
    #: not a screen's. A screen renders these as buttons, labelled from the
    #: contract, and applies its own judgement about which it is willing to put
    #: one tap away — `delete` takes no payload and still does not get one.
    run_operations: list[str] = Field(default_factory=list)
    options: list[ManagedOption] = Field(default_factory=list)
    constraints: ManagedConstraints | None = None
    #: Hebrew — why this item cannot be operated right now.
    unavailable_reason: str | None = None
    #: Extra canonical, already-safe fields for a family's own screen: a rule's
    #: days, an event's start and end, a device's mode. Never a raw entity id —
    #: the normalizers drop those before they get here.
    detail: dict[str, Any] = Field(default_factory=dict)


class ManagedGroup(CanonicalModel):
    """A titled section of a resource screen."""

    id: str
    label: str
    description: str | None = None
    items: list[ManagedItem] = Field(default_factory=list)


class ResourceSnapshot(CanonicalModel):
    """One family's current state, normalized.

    The same envelope for settings, users, Shabbat, rules, the calendar, devices
    and the system. `available` false with a Hebrew `reason` is a perfectly good
    answer and the screens are built to show it: a bridge that has not landed
    yet is reported as missing, never worked around.
    """

    resource: str
    available: bool = False
    reason: str | None = None
    #: Home Assistant's master switch, as reported on this call.
    writes_enabled: bool = False
    groups: list[ManagedGroup] = Field(default_factory=list)
    #: Every item, flat, whatever group it sits in.
    items: list[ManagedItem] = Field(default_factory=list)
    #: The family's own canonical extras — a Shabbat profile list, a calendar
    #: range, the device classes present. Already normalized and already safe.
    detail: dict[str, Any] = Field(default_factory=dict)


# --- the bridge specification -----------------------------------------------
class BridgeField(CanonicalModel):
    """One input a bridge service receives, or one output it returns."""

    name: str
    type: str
    note: str


class BridgeServiceContract(CanonicalModel):
    """Everything the Home Assistant side needs to implement one bridge."""

    #: `script.` + this is the service to create.
    name: str
    #: `read` or `write`.
    kind: str
    purpose: str
    #: The managed family it serves, when it serves one.
    resource: str | None = None
    operations: list[str] = Field(default_factory=list)
    inputs: list[BridgeField] = Field(default_factory=list)
    #: The response shape, as a documented example.
    outputs: str = ""
    validation: list[str] = Field(default_factory=list)
    verification: str = ""
    #: The highest risk any of its operations carries.
    risk: str = "read_only"
    #: Per-operation risk, so both sides rate the same change the same way.
    operation_risk: dict[str, str] = Field(default_factory=dict)


class BridgeContract(CanonicalModel):
    """The full specification, and which parts of it are already live."""

    app_version: str
    #: Services Home Assistant has implemented, per the live contract.
    implemented: list[str] = Field(default_factory=list)
    #: Services this build calls but the live contract does not declare.
    missing: list[str] = Field(default_factory=list)
    services: list[BridgeServiceContract] = Field(default_factory=list)
    #: Sent on every commit, whatever the family.
    common_commit_inputs: list[BridgeField] = Field(default_factory=list)
    common_commit_outputs: list[BridgeField] = Field(default_factory=list)
    #: Home Assistant domains this application never calls.
    never_called_domains: list[str] = Field(default_factory=list)
    #: Operations it refuses to ask for, however they are advertised.
    never_requested: list[str] = Field(default_factory=list)
    #: risk → the least privileged role allowed to run it.
    risk_to_role: dict[str, str] = Field(default_factory=dict)
