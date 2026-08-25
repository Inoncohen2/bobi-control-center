"""The Bobi Control Center bridge contract.

These models mirror what the `script.bobi_cc_*` services return. They are the
contract between Home Assistant and this application, and both adapters — real
and mock — must satisfy them, so the frontend renders one shape regardless of
which is active.

Two deliberate choices run through this module:

* **Every model allows extra fields.** The bridge is Bobi's canonical registry
  and is expected to grow. Unknown keys are preserved rather than dropped, so a
  new capability or device field appears in the UI's Advanced panel instead of
  silently vanishing.
* **Almost every field is optional.** A partially-populated bridge response must
  degrade to a usable screen, not a 500.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BridgeModel(BaseModel):
    """Base for everything the bridge returns."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def extras(self) -> dict[str, object]:
        """Fields the bridge sent that this model does not declare."""
        return dict(self.__pydantic_extra__ or {})


# --- status -----------------------------------------------------------------
class StatusComponent(BridgeModel):
    """One health row, e.g. WhatsApp / connected."""

    id: str | None = None
    name: str | None = None
    state: str | None = None
    label: str | None = None
    detail: str | None = None
    ok: bool | None = None


class BridgeStatus(BridgeModel):
    """`script.bobi_cc_status`."""

    ok: bool | None = None
    version: str | None = None
    uptime: str | None = None
    components: list[StatusComponent] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    #: Bobi's own statement about whether writes are permitted. Phase 2 treats
    #: anything other than an explicit True as False.
    writes_enabled: bool = False


# --- devices ----------------------------------------------------------------
class DeviceLimits(BridgeModel):
    """Per-device constraints, e.g. min/max temperature."""

    min: float | None = None
    max: float | None = None
    step: float | None = None


class BridgeDevice(BridgeModel):
    """One entry of Bobi's canonical entity catalog.

    `entity_id` and `handler` are technical and must only ever be rendered
    inside the UI's "מתקדם / פרטים טכניים" disclosure.
    """

    entity_id: str | None = None
    name: str | None = None
    #: The human-facing name. Preferred over `name` everywhere in the UI.
    canonical: str | None = None
    semantic_scopes: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    group: str | None = None
    area: str | None = None
    state: str | None = None
    controllable: bool | None = None
    logical_controllable: bool | None = None
    handler: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    limits: DeviceLimits | None = None
    last_changed: str | None = None

    @property
    def display_name(self) -> str:
        return self.canonical or self.name or self.entity_id or "מכשיר ללא שם"

    @property
    def available(self) -> bool:
        return (self.state or "").lower() not in {"unavailable", "unknown", ""}


class BridgeDevices(BridgeModel):
    """`script.bobi_cc_devices`."""

    scope: str | None = None
    include_unavailable: bool | None = None
    count: int | None = None
    devices: list[BridgeDevice] = Field(default_factory=list)

    @property
    def areas(self) -> list[str]:
        return sorted({d.area for d in self.devices if d.area})

    @property
    def groups(self) -> list[str]:
        return sorted({d.group for d in self.devices if d.group})


#: Scopes the bridge accepts for `script.bobi_cc_devices`.
DEVICE_SCOPES = (
    "all",
    "lighting",
    "climate",
    "cameras",
    "battery",
    "temperature",
    "humidity",
    "vacuum",
    "people",
    "switches",
    "scent",
)


# --- capabilities -----------------------------------------------------------
class BridgeCapability(BridgeModel):
    """One entry of Bobi's canonical Capability Registry.

    Rendered dynamically: the UI must not hard-code a known set, because the
    registry is the source of truth and grows independently of this app.
    """

    id: str | None = None
    handler: str | None = None
    local: bool | None = None
    local_after_parse: bool | None = None
    risk: str | None = None
    label: str | None = None
    example: str | None = None
    group: str | None = None

    @property
    def key(self) -> str:
        return self.id or self.handler or self.label or "capability"


class CapabilityToggle(BridgeModel):
    """A runtime master switch. READ-ONLY in Phase 2."""

    id: str | None = None
    name: str | None = None
    label: str | None = None
    state: str | None = None
    enabled: bool | None = None
    entity_id: str | None = None


class BridgeCapabilities(BridgeModel):
    """`script.bobi_cc_capabilities`."""

    count: int | None = None
    capabilities: list[BridgeCapability] = Field(default_factory=list)
    #: Runtime state for capabilities that have a master toggle.
    toggles: list[CapabilityToggle] = Field(default_factory=list)


# --- users ------------------------------------------------------------------
class BridgeUser(BridgeModel):
    """A household member.

    The bridge deliberately omits WhatsApp numbers and LIDs; this app must not
    reintroduce them from any other source.
    """

    id: str | None = None
    name: str | None = None
    role: str | None = None
    enabled: bool | None = None
    whatsapp_connected: bool | None = None
    calendar: str | None = None
    task_list: str | None = None
    permissions: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)


class BridgeUsers(BridgeModel):
    """`script.bobi_cc_users`."""

    count: int | None = None
    users: list[BridgeUser] = Field(default_factory=list)


# --- probe ------------------------------------------------------------------
class ProbeUnderstanding(BridgeModel):
    """What Bobi understood. Shape varies by skill, so it stays open."""

    intent: str | None = None
    action: str | None = None
    domain: str | None = None
    target: str | None = None
    targets: list[str] = Field(default_factory=list)
    area: str | None = None
    value: object | None = None
    time: str | None = None
    date: str | None = None


class BridgeProbe(BridgeModel):
    """`script.bobi_cc_probe`, invoked by the bridge with probe_only=true.

    This never executes. `would_execute` is not a bridge field — it is asserted
    by this application and always False.
    """

    handled: bool | None = None
    status: str | None = None
    terminal: bool | None = None
    skill: str | None = None
    understanding: ProbeUnderstanding | None = None
    schedule_valid: bool | None = None
    schedule_reason: str | None = None
    schedule_kind: str | None = None
    text: str | None = None
    error: str | None = None

    #: Invariant of the Phase 2 contract, restated in every response.
    probe_only: bool = True
    would_execute: bool = False


# --- shabbat ----------------------------------------------------------------
class ShabbatProfile(BridgeModel):
    """A pre-off / pre-on / night-off / morning-on profile."""

    id: str | None = None
    name: str | None = None
    label: str | None = None
    active: bool | None = None
    devices: list[str] = Field(default_factory=list)
    time: str | None = None
    offset_minutes: int | None = None


class BridgeShabbat(BridgeModel):
    """`script.bobi_cc_shabbat`. READ-ONLY in Phase 2."""

    candle_lighting: str | None = None
    havdalah: str | None = None
    pre_shabbat_offset_minutes: int | None = None
    pre_off_profile: ShabbatProfile | None = None
    pre_on_profile: ShabbatProfile | None = None
    night_off_profile: ShabbatProfile | None = None
    morning_on_profile: ShabbatProfile | None = None
    ac_temperatures: dict[str, object] = Field(default_factory=dict)
    #: device token → friendly label, so the UI never shows a raw token.
    device_labels: dict[str, str] = Field(default_factory=dict)
    has_draft: bool | None = None
    #: False for the whole of Phase 2.
    writes_enabled: bool = False

    def label_for(self, token: str) -> str:
        return self.device_labels.get(token, token)


# --- rules ------------------------------------------------------------------
class BridgeRule(BridgeModel):
    """One of Bobi's canonical smart rules — not a raw HA automation."""

    id: str | None = None
    name: str | None = None
    label: str | None = None
    description: str | None = None
    enabled: bool | None = None
    kind: str | None = None
    trigger: str | None = None
    schedule: str | None = None
    targets: list[str] = Field(default_factory=list)
    last_triggered: str | None = None
    entity_id: str | None = None


class BridgeRules(BridgeModel):
    """`script.bobi_cc_rules`."""

    count: int | None = None
    rules: list[BridgeRule] = Field(default_factory=list)


# --- tasks ------------------------------------------------------------------
class BridgeTask(BridgeModel):
    """A task. The bridge already strips internal metadata."""

    id: str | None = None
    title: str | None = None
    summary: str | None = None
    status: str | None = None
    completed: bool | None = None
    due: str | None = None
    owner: str | None = None
    list_name: str | None = None

    @property
    def is_done(self) -> bool:
        if self.completed is not None:
            return self.completed
        return (self.status or "").lower() in {"completed", "done"}

    @property
    def display_title(self) -> str:
        return self.title or self.summary or "משימה"


class BridgeTasks(BridgeModel):
    """`script.bobi_cc_tasks`."""

    count: int | None = None
    tasks: list[BridgeTask] = Field(default_factory=list)


# --- diagnostics ------------------------------------------------------------
class DiagnosticCheck(BridgeModel):
    """One health check the bridge ran."""

    id: str | None = None
    name: str | None = None
    label: str | None = None
    ok: bool | None = None
    detail: str | None = None


class BridgeIssue(BridgeModel):
    """A problem worth a person's attention.

    May carry technical entity ids; the UI keeps those in a collapsed
    "פרטים טכניים" section.
    """

    id: str | None = None
    severity: str | None = None
    title: str | None = None
    label: str | None = None
    message: str | None = None
    description: str | None = None
    component: str | None = None
    entity_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    detail: str | None = None

    @property
    def display_title(self) -> str:
        return self.title or self.label or self.message or "בעיה לא מזוהה"

    @property
    def display_severity(self) -> str:
        value = (self.severity or "").lower()
        return value if value in {"ok", "warning", "error"} else "warning"


class BridgeDiagnostics(BridgeModel):
    """`script.bobi_cc_diagnostics`."""

    ok: bool | None = None
    issue_count: int | None = None
    issues: list[BridgeIssue] = Field(default_factory=list)
    checks: list[DiagnosticCheck] = Field(default_factory=list)


# --- connection -------------------------------------------------------------
class ConnectionInfo(BaseModel):
    """How this app is currently getting its data.

    Surfaced by `/health` and `/api/bobi/connection` so the UI can tell the user
    plainly whether it is showing real data or demo data. Contains no secret.
    """

    model_config = ConfigDict(populate_by_name=True)

    adapter: str
    connected: bool
    #: Always False in Phase 2, whatever the bridge reports.
    writes_enabled: bool = False
    phase: int = 2
    detail: str | None = None
