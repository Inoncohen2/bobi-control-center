"""The canonical Bobi Control Center contract.

These are the models the API returns and the frontend consumes. They are **not**
the shape Home Assistant sends — `app/services/normalize.py` maps the raw bridge
response onto these, and is the only place that knows about bridge field names.

Two rules make this a clean contract:

* **One representation per resource.** A response carries exactly one device
  list, one capability list, one task list. There is never a populated
  collection sitting beside an empty legacy one.
* **Nothing is silently dropped.** Fields the normalizer does not map explicitly
  land in a per-item `extra` dict, which the UI shows under
  "מתקדם / פרטים טכניים". A growing registry surfaces there rather than
  disappearing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalModel(BaseModel):
    """Base for every response model.

    `extra="ignore"`: these are built by the normalizer, so unexpected input
    keys must not leak into the response and recreate the duplicate-schema
    problem this contract exists to solve.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# --- status -----------------------------------------------------------------
class StatusComponent(CanonicalModel):
    """One health row on the dashboard."""

    id: str
    name: str
    label: str
    state: str | None = None
    ok: bool | None = None
    detail: str | None = None


class WhatsAppStatus(CanonicalModel):
    """Bobi's messaging channel."""

    connected: bool | None = None
    status: str | None = None
    label: str | None = None
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AiStatus(CanonicalModel):
    """The language-model fallback and its fast paths.

    `fast_paths` is normalized from whatever the bridge sends — a flag, a count,
    or a list of path names — into a flag plus a count, so the dashboard can
    show it either way.
    """

    enabled: bool | None = None
    fast_paths_enabled: bool | None = None
    fast_paths_count: int | None = None
    fast_paths: list[str] = Field(default_factory=list)
    label: str | None = None
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class UsersSummary(CanonicalModel):
    """How many household members Bobi is serving."""

    total: int | None = None
    active: int | None = None
    admins: int | None = None
    names: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class FeatureFlag(CanonicalModel):
    """One feature toggle Bobi reports. READ-ONLY in Phase 2."""

    id: str
    label: str
    enabled: bool | None = None
    detail: str | None = None


class ConfigStatus(CanonicalModel):
    """Health of Bobi's own configuration."""

    ok: bool | None = None
    status: str | None = None
    label: str | None = None
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeHealth(CanonicalModel):
    """Bobi's overall health, as one resolved answer.

    The bridge does not always send a field called `ok`; in the real install it
    reports `healthy` instead, which used to land in `details` as the string
    `"True"` while `ok` stayed null. So health is resolved here, from
    authoritative information only:

    * whatever the bridge states about itself wins — `ok`, `healthy`, or a
      status word;
    * failing that, it is derived from the component states, where **only an
      explicit failure counts**. A component whose state is unknown leaves
      health unknown; it never makes it `false`.

    `unknown` is a real answer and must be rendered as such. It is not a
    failure, and the UI must never colour it like one.
    """

    #: `healthy` · `degraded` · `unhealthy` · `unknown`.
    status: str = "unknown"
    #: `None` when genuinely unknown — never coerced to a boolean.
    ok: bool | None = None
    #: Why, in a sentence a person can read.
    reason: str | None = None


#: The health states, in the order of a worsening system.
HEALTH_STATES = ("healthy", "degraded", "unhealthy", "unknown")


class BridgeStatus(CanonicalModel):
    """Normalized `script.bobi_cc_status`.

    The bridge reports far more than a flat health list, so the real sections
    are first-class fields rather than being flattened into `details`.
    """

    #: The resolved overall answer. `ok` below mirrors `health.ok`.
    health: BridgeHealth = Field(default_factory=BridgeHealth)
    ok: bool | None = None
    version: str | None = None
    uptime: str | None = None

    #: Structured sections the dashboard renders directly.
    whatsapp: WhatsAppStatus | None = None
    ai: AiStatus | None = None
    users: UsersSummary | None = None
    config: ConfigStatus | None = None
    features: list[FeatureFlag] = Field(default_factory=list)

    #: Health cards. Derived from the sections above when the bridge does not
    #: send an explicit list, so the dashboard always has a top row.
    components: list[StatusComponent] = Field(default_factory=list)

    #: Numeric headline figures, rendered dynamically.
    counts: dict[str, int] = Field(default_factory=dict)
    #: Whatever scalar fields remain, shown as a details list rather than
    #: discarded.
    details: dict[str, str] = Field(default_factory=dict)
    #: Phase 2 invariant, never taken from the bridge.
    writes_enabled: bool = False


# --- devices ----------------------------------------------------------------
class DeviceLimits(CanonicalModel):
    """A device's constraints, preserved in full.

    Bobi's catalog carries domain-specific limits — temperature ranges and mode
    lists for climate, colour temperature for lights, intensity and slots for
    the scent diffuser. Collapsing them to a bare min/max/step threw away what
    the editing controls will need, so every documented field is kept and
    anything else lands in `extra`.

    `min`/`max`/`step` remain as a generic view, filled from the domain-specific
    values where there is an unambiguous equivalent.
    """

    # Generic view.
    min: float | None = None
    max: float | None = None
    step: float | None = None

    # Climate.
    min_temp: float | None = None
    max_temp: float | None = None
    temp_step: float | None = None
    preset_modes: list[str] = Field(default_factory=list)
    fan_modes: list[str] = Field(default_factory=list)
    swing_modes: list[str] = Field(default_factory=list)
    hvac_modes: list[str] = Field(default_factory=list)

    # Lights.
    min_kelvin: float | None = None
    max_kelvin: float | None = None
    min_brightness: float | None = None
    max_brightness: float | None = None

    # Scent diffuser.
    intensity_min: float | None = None
    intensity_max: float | None = None
    scent_slots: list[str] = Field(default_factory=list)
    timer_max_seconds: int | None = None

    #: Anything the bridge sends that is not listed above.
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeDevice(CanonicalModel):
    """One device from Bobi's canonical entity catalog.

    `entity_id` and `handler` are technical: the UI shows them only inside the
    Advanced disclosure.
    """

    #: Stable key for React. Falls back through entity_id → name.
    id: str
    #: The user-facing name. Never an entity id.
    name: str
    area: str | None = None
    group: str | None = None
    domain: str | None = None
    state: str | None = None
    available: bool = True
    aliases: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    semantic_scopes: list[str] = Field(default_factory=list)
    controllable: bool | None = None
    logical_controllable: bool | None = None
    entity_id: str | None = None
    handler: str | None = None
    limits: DeviceLimits | None = None
    last_changed: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeDevices(CanonicalModel):
    """Normalized `script.bobi_cc_devices`."""

    scope: str = "all"
    include_unavailable: bool = True
    count: int = 0
    devices: list[BridgeDevice] = Field(default_factory=list)
    #: Derived server-side so the UI does not recompute them.
    areas: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


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
class BridgeCapability(CanonicalModel):
    """One entry of Bobi's canonical Capability Registry."""

    id: str
    label: str
    example: str | None = None
    risk: str | None = None
    handler: str | None = None
    local: bool | None = None
    local_after_parse: bool | None = None
    group: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CapabilityToggle(CanonicalModel):
    """A runtime master switch. READ-ONLY in Phase 2."""

    id: str
    label: str
    enabled: bool | None = None
    state: str | None = None
    entity_id: str | None = None


class BridgeCapabilities(CanonicalModel):
    """Normalized `script.bobi_cc_capabilities`."""

    count: int = 0
    capabilities: list[BridgeCapability] = Field(default_factory=list)
    toggles: list[CapabilityToggle] = Field(default_factory=list)


# --- users ------------------------------------------------------------------
class BridgeUser(CanonicalModel):
    """A household member.

    Never carries a WhatsApp number or LID: the bridge withholds them and this
    app must not reintroduce them.
    """

    id: str
    name: str
    role: str | None = None
    enabled: bool | None = None
    whatsapp_connected: bool | None = None
    calendar: str | None = None
    task_list: str | None = None
    permissions: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeUsers(CanonicalModel):
    """Normalized `script.bobi_cc_users`."""

    count: int = 0
    users: list[BridgeUser] = Field(default_factory=list)


# --- probe ------------------------------------------------------------------
class BridgeProbe(CanonicalModel):
    """Normalized `script.bobi_cc_probe`.

    The bridge nests its real answer under `result`; the normalizer flattens
    that so the frontend sees one flat shape.
    """

    handled: bool | None = None
    status: str | None = None
    terminal: bool | None = None
    skill: str | None = None
    #: Shape varies by skill, so it stays an open map and is rendered generically.
    understanding: dict[str, Any] = Field(default_factory=dict)
    schedule_valid: bool | None = None
    schedule_reason: str | None = None
    schedule_kind: str | None = None
    text: str | None = None
    error: str | None = None
    #: Anything worth telling the user, including a bridge that unexpectedly
    #: reported execution.
    warnings: list[str] = Field(default_factory=list)

    #: Invariants of the Phase 2 contract, asserted here regardless of input.
    probe_only: bool = True
    would_execute: bool = False

    #: The unmodified bridge response, for the Test Center's JSON view.
    raw: dict[str, Any] = Field(default_factory=dict)


# --- shabbat ----------------------------------------------------------------
class ProfileDevice(CanonicalModel):
    """A device inside a Shabbat profile.

    Both halves are kept: `id` is the bridge's own token, which Phase 3 will
    need in order to write a change back, and `label` is what a person reads.
    """

    id: str
    label: str


class ShabbatAcTemperature(CanonicalModel):
    """A temperature tied to the air conditioner it belongs to.

    The bridge keeps these inside the profiles rather than at the top level, so
    they are collected from wherever they appear and de-duplicated by device.
    """

    id: str
    label: str
    #: The numeric value, for the editing controls Phase 3 will add. `None`
    #: when the bridge sent something that is not a number — never guessed.
    temperature: float | None = None
    #: Exactly what the bridge sent, so a non-numeric setting is still shown.
    text: str | None = None


class ShabbatProfile(CanonicalModel):
    """One Shabbat profile.

    `kind` carries the bridge's own profile key (`pre_off`, `night_on`, …) so
    the UI can render whatever set the bridge defines instead of a fixed four.
    """

    id: str
    kind: str
    label: str
    active: bool | None = None
    time: str | None = None
    offset_minutes: int | None = None
    #: Resolved from the bridge's device tokens, keeping both id and label.
    devices: list[ProfileDevice] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeShabbat(CanonicalModel):
    """Normalized `script.bobi_cc_shabbat`. READ-ONLY in Phase 2."""

    #: A time of day — "18:51" — not a timestamp.
    #:
    #: The `jewish_calendar` sensors hold a UTC instant, and this house is three
    #: hours ahead of it. Passing the sensor through put `2026-08-28T15:51:00+00:00`
    #: on the screen: the wrong hour, in a format nobody reads, where a household
    #: wants the two numbers it plans its Friday around.
    candle_lighting: str | None = None
    havdalah: str | None = None
    #: The full local instant, kept beside the clock for anything that needs to
    #: compute with it rather than read it.
    candle_lighting_at: str | None = None
    havdalah_at: str | None = None
    parasha: str | None = None
    #: "ט\"ו אלול ה' תשפ\"ו", and the festival when there is one.
    hebrew_date: str | None = None
    holiday: str | None = None
    pre_shabbat_offset_minutes: int | None = None
    profiles: list[ShabbatProfile] = Field(default_factory=list)
    #: Each temperature stays tied to its air conditioner, id and label both.
    ac_temperatures: list[ShabbatAcTemperature] = Field(default_factory=list)
    has_draft: bool = False
    draft_owners: list[str] = Field(default_factory=list)
    #: False for the whole of Phase 2.
    writes_enabled: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


# --- rules ------------------------------------------------------------------
class BridgeRule(CanonicalModel):
    """One of Bobi's canonical smart rules — not a raw HA automation."""

    id: str
    name: str
    description: str | None = None
    enabled: bool | None = None
    kind: str | None = None
    trigger: str | None = None
    schedule: str | None = None
    targets: list[str] = Field(default_factory=list)
    last_triggered: str | None = None
    entity_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeRules(CanonicalModel):
    """Normalized `script.bobi_cc_rules`."""

    count: int = 0
    rules: list[BridgeRule] = Field(default_factory=list)


# --- tasks ------------------------------------------------------------------
class BridgeTask(CanonicalModel):
    """A task. The bridge already strips internal metadata."""

    id: str
    title: str
    owner: str | None = None
    completed: bool = False
    status: str | None = None
    due: str | None = None
    list_name: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeTasks(CanonicalModel):
    """Normalized `script.bobi_cc_tasks`.

    The bridge groups tasks per user; the normalizer flattens them into one list
    with `owner` set, and keeps the per-owner counts.
    """

    count: int = 0
    tasks: list[BridgeTask] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)


# --- diagnostics ------------------------------------------------------------
class DiagnosticCheck(CanonicalModel):
    """One health check.

    The bridge sends `checks` as a **map** of name → value, where a value may be
    a status word (`"WORKING"`) or a number (`catalog_count: 19`). Both become a
    check: `ok` is set when the value reads as a pass/fail, and left `None` for
    an informational figure.
    """

    id: str
    label: str
    ok: bool | None = None
    value: str | None = None
    detail: str | None = None


class BridgeIssue(CanonicalModel):
    """A problem worth a person's attention.

    `code` and `entity_ids` are technical and belong in the collapsed
    "פרטים טכניים" section.
    """

    id: str
    severity: str = "warning"
    title: str
    message: str | None = None
    component: str | None = None
    code: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class BridgeDiagnostics(CanonicalModel):
    """Normalized `script.bobi_cc_diagnostics`."""

    ok: bool | None = None
    issue_count: int = 0
    issues: list[BridgeIssue] = Field(default_factory=list)
    checks: list[DiagnosticCheck] = Field(default_factory=list)


# --- connection -------------------------------------------------------------
class ConnectionInfo(CanonicalModel):
    """How this app is currently getting its data. Contains no secret."""

    adapter: str
    connected: bool
    writes_enabled: bool = False
    phase: int = 2
    #: This application's version, so the UI never hard-codes it.
    app_version: str = ""
    detail: str | None = None


# --- cameras ----------------------------------------------------------------
class CameraFrame(CanonicalModel):
    """One still picture, on its way to the browser.

    Not a URL. A URL to Home Assistant would have to carry either the entity id
    or the camera's own access token, and neither may leave this process, so the
    bytes themselves are the response.
    """

    #: The encoded image, exactly as Home Assistant returned it.
    image: bytes
    #: Echoed from the upstream response so the browser renders what arrived
    #: rather than what this app guessed.
    content_type: str = "image/jpeg"
