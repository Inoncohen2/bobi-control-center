/**
 * TypeScript mirror of the backend's **canonical** contract.
 *
 * These are not the shapes Home Assistant sends. The backend's
 * `app/services/normalize.py` maps the raw bridge response onto these, so React
 * receives one clean schema and contains no normalization logic of its own.
 *
 * Every item carries an `extra` map holding fields the normalizer did not map
 * explicitly — rendered in the "מתקדם / פרטים טכניים" disclosure so a growing
 * registry surfaces rather than disappearing.
 *
 * `entity_id` and `handler` are technical: display them only inside that
 * disclosure.
 */

export type Extra = Record<string, unknown>;

// --- connection ------------------------------------------------------------
export interface ConnectionInfo {
  adapter: string;
  connected: boolean;
  /** Always false in Phase 2. */
  writes_enabled: boolean;
  phase: number;
  /** The running app version, so the UI never hard-codes it. */
  app_version: string;
  detail: string | null;
}

// --- status ----------------------------------------------------------------
export interface StatusComponent {
  id: string;
  name: string;
  label: string;
  state: string | null;
  ok: boolean | null;
  detail: string | null;
}

/** Bobi's messaging channel. */
export interface WhatsAppStatus {
  connected: boolean | null;
  status: string | null;
  label: string | null;
  detail: string | null;
  extra: Extra;
}

/** The language-model fallback and its fast paths. */
export interface AiStatus {
  enabled: boolean | null;
  fast_paths_enabled: boolean | null;
  fast_paths_count: number | null;
  fast_paths: string[];
  label: string | null;
  detail: string | null;
  extra: Extra;
}

/** How many household members Bobi is serving. */
export interface UsersSummary {
  total: number | null;
  active: number | null;
  admins: number | null;
  names: string[];
  extra: Extra;
}

/** One feature toggle Bobi reports. READ-ONLY in Phase 2. */
export interface FeatureFlag {
  id: string;
  label: string;
  enabled: boolean | null;
  detail: string | null;
}

/** Health of Bobi's own configuration. */
export interface ConfigStatus {
  ok: boolean | null;
  status: string | null;
  label: string | null;
  detail: string | null;
  extra: Extra;
}

/**
 * Bobi's overall health, resolved server-side.
 *
 * `unknown` is a real answer, not a failure: the bridge did not say. Render it
 * as unknown — never as a problem, and never as a red state.
 */
export interface BridgeHealth {
  /** `healthy` · `degraded` · `unhealthy` · `unknown`. */
  status: string;
  /** `null` when genuinely unknown. Never coerced to a boolean. */
  ok: boolean | null;
  reason: string | null;
}

export interface BridgeStatus {
  /** The resolved overall answer; `ok` below mirrors `health.ok`. */
  health: BridgeHealth;
  ok: boolean | null;
  version: string | null;
  uptime: string | null;
  /** Structured sections, rendered directly rather than as text rows. */
  whatsapp: WhatsAppStatus | null;
  ai: AiStatus | null;
  users: UsersSummary | null;
  config: ConfigStatus | null;
  features: FeatureFlag[];
  /** Health cards, derived server-side when the bridge sends no list. */
  components: StatusComponent[];
  /** Numeric headline figures, rendered dynamically. */
  counts: Record<string, number>;
  /** Remaining scalar fields the bridge sent. */
  details: Record<string, string>;
  writes_enabled: boolean;
}

// --- devices ---------------------------------------------------------------
/**
 * A device's constraints, preserved in full.
 *
 * `min`/`max`/`step` are a generic view the backend fills from whichever
 * domain-specific range applies; the domain fields below are the real ones and
 * are what Phase 3's editing controls will use.
 */
export interface DeviceLimits {
  min: number | null;
  max: number | null;
  step: number | null;
  // Climate.
  min_temp: number | null;
  max_temp: number | null;
  temp_step: number | null;
  preset_modes: string[];
  fan_modes: string[];
  swing_modes: string[];
  hvac_modes: string[];
  // Lights.
  min_kelvin: number | null;
  max_kelvin: number | null;
  min_brightness: number | null;
  max_brightness: number | null;
  // Scent diffuser.
  intensity_min: number | null;
  intensity_max: number | null;
  scent_slots: string[];
  timer_max_seconds: number | null;
  /** Anything the bridge sends that is not listed above. */
  extra: Extra;
}

export interface BridgeDevice {
  /** Stable key. */
  id: string;
  /** The user-facing name. Never an entity id. */
  name: string;
  area: string | null;
  group: string | null;
  domain: string | null;
  state: string | null;
  available: boolean;
  aliases: string[];
  capabilities: string[];
  semantic_scopes: string[];
  controllable: boolean | null;
  logical_controllable: boolean | null;
  entity_id: string | null;
  handler: string | null;
  limits: DeviceLimits | null;
  last_changed: string | null;
  extra: Extra;
}

export interface BridgeDevices {
  scope: string;
  include_unavailable: boolean;
  count: number;
  devices: BridgeDevice[];
  /** Derived server-side. */
  areas: string[];
  groups: string[];
}

export const DEVICE_SCOPES = [
  'all',
  'lighting',
  'climate',
  'cameras',
  'battery',
  'temperature',
  'humidity',
  'vacuum',
  'people',
  'switches',
  'scent',
] as const;

export type DeviceScope = (typeof DEVICE_SCOPES)[number];

// --- capabilities ----------------------------------------------------------
export interface BridgeCapability {
  id: string;
  label: string;
  example: string | null;
  risk: string | null;
  handler: string | null;
  local: boolean | null;
  local_after_parse: boolean | null;
  group: string | null;
  extra: Extra;
}

/** A runtime master switch. READ-ONLY in Phase 2. */
export interface CapabilityToggle {
  id: string;
  label: string;
  enabled: boolean | null;
  state: string | null;
  entity_id: string | null;
}

export interface BridgeCapabilities {
  count: number;
  capabilities: BridgeCapability[];
  toggles: CapabilityToggle[];
}

// --- users -----------------------------------------------------------------
export interface BridgeUser {
  id: string;
  name: string;
  role: string | null;
  enabled: boolean | null;
  whatsapp_connected: boolean | null;
  calendar: string | null;
  task_list: string | null;
  permissions: string[];
  areas: string[];
  extra: Extra;
}

export interface BridgeUsers {
  count: number;
  users: BridgeUser[];
}

// --- probe -----------------------------------------------------------------
export interface BridgeProbe {
  handled: boolean | null;
  status: string | null;
  terminal: boolean | null;
  skill: string | null;
  /** Shape varies by skill, so it is rendered generically. */
  understanding: Record<string, unknown>;
  schedule_valid: boolean | null;
  schedule_reason: string | null;
  schedule_kind: string | null;
  text: string | null;
  error: string | null;
  warnings: string[];
  /** Invariants of the Phase 2 contract. */
  probe_only: boolean;
  would_execute: boolean;
  /** The unmodified bridge response, for the JSON view. */
  raw: Record<string, unknown>;
}

// --- shabbat ---------------------------------------------------------------
/**
 * A device inside a Shabbat profile.
 *
 * `id` is the bridge's own token — kept because Phase 3 must send it back to
 * change the profile — and `label` is what a person reads.
 */
export interface ProfileDevice {
  id: string;
  label: string;
}

/** A temperature tied to the air conditioner it belongs to. */
export interface ShabbatAcTemperature {
  id: string;
  label: string;
  /** Numeric value, or null when the bridge sent something non-numeric. */
  temperature: number | null;
  /** Exactly what the bridge sent, so a setting like "auto" still shows. */
  text: string | null;
}

export interface ShabbatProfile {
  id: string;
  /** The bridge's own profile key, e.g. `pre_off`. */
  kind: string;
  label: string;
  active: boolean | null;
  time: string | null;
  offset_minutes: number | null;
  /** Resolved from the bridge's tokens by the backend, id and label both. */
  devices: ProfileDevice[];
  extra: Extra;
}

export interface BridgeShabbat {
  /** A time of day — "18:51" — never a timestamp. */
  candle_lighting: string | null;
  havdalah: string | null;
  /** The full local instant, for anything that computes rather than reads. */
  candle_lighting_at: string | null;
  havdalah_at: string | null;
  parasha: string | null;
  hebrew_date: string | null;
  /** Null when it is an ordinary week, so the card shows no empty label. */
  holiday: string | null;
  pre_shabbat_offset_minutes: number | null;
  profiles: ShabbatProfile[];
  /** Each temperature stays tied to its air conditioner. */
  ac_temperatures: ShabbatAcTemperature[];
  has_draft: boolean;
  draft_owners: string[];
  /** False for the whole of Phase 2. */
  writes_enabled: boolean;
  extra: Extra;
}

// --- rules -----------------------------------------------------------------
export interface BridgeRule {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean | null;
  kind: string | null;
  trigger: string | null;
  schedule: string | null;
  targets: string[];
  last_triggered: string | null;
  entity_id: string | null;
  extra: Extra;
}

export interface BridgeRules {
  count: number;
  rules: BridgeRule[];
}

// --- tasks -----------------------------------------------------------------
export interface BridgeTask {
  id: string;
  title: string;
  owner: string | null;
  completed: boolean;
  status: string | null;
  due: string | null;
  list_name: string | null;
  extra: Extra;
}

export interface BridgeTasks {
  count: number;
  tasks: BridgeTask[];
  owners: string[];
}

// --- diagnostics -----------------------------------------------------------
export interface DiagnosticCheck {
  id: string;
  label: string;
  /** null for an informational figure such as a count. */
  ok: boolean | null;
  value: string | null;
  detail: string | null;
}

export interface BridgeIssue {
  id: string;
  severity: string;
  title: string;
  message: string | null;
  component: string | null;
  /** Technical: show only under פרטים טכניים. */
  code: string | null;
  entity_ids: string[];
  suggested_action: string | null;
  detail: string | null;
  extra: Extra;
}

export interface BridgeDiagnostics {
  ok: boolean | null;
  issue_count: number;
  issues: BridgeIssue[];
  checks: DiagnosticCheck[];
}

/** The backend's structured error envelope. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

// --- management (Phase 3A) -------------------------------------------------
/**
 * The write flow: edit → preview → confirm → commit → verify → result.
 *
 * Nothing here is optimistic. A commit reports one of three outcomes, and the
 * UI must not show a saved state until the read-back agrees.
 */

/** One reason a change cannot proceed. `message` is Hebrew, for display. */
export interface ManageValidationError {
  field: string | null;
  code: string;
  message: string;
}

/** One before/after row of a preview, already rendered as text. */
export interface ChangeField {
  label: string;
  before: string | null;
  after: string | null;
}

export interface PreviewRequest {
  operation: string;
  resource_id?: string | null;
  payload?: Record<string, unknown>;
}

export interface PreviewResponse {
  /** Single-use; the matching commit requires it. */
  preview_id: string;
  operation: string;
  resource_type: string;
  resource_id: string | null;
  title: string;
  changes: ChangeField[];
  explanation: string | null;
  destructive: boolean;
  warning: string | null;
  /** The word the user must type to confirm a destructive change. */
  confirm_word: string | null;
  confirm_label: string;
  valid: boolean;
  errors: ManageValidationError[];
  expires_at: string;
  /** A preview never writes. */
  would_execute: boolean;
}

export interface CommitRequest {
  preview_id: string;
  confirmed: boolean;
  confirm_word?: string | null;
  /** Echoed back and checked against the stored preview. */
  operation?: string | null;
  resource_id?: string | null;
}

export interface VerificationResult {
  verified: boolean;
  method: string | null;
  detail: string | null;
}

export interface WriteResult {
  /** `committed` · `committed_unverified` · `failed`. */
  status: string;
  /** Hebrew, exactly what the screen shows. */
  message: string;
  resource_id: string | null;
  /** The bridge's own reason token, for the technical view. */
  reason: string | null;
  verification: VerificationResult;
}

export interface AuditEntry {
  id: string;
  timestamp: string;
  stage: string;
  operation: string;
  resource_type: string;
  resource_id: string | null;
  requested_change: Record<string, unknown>;
  result: string;
  verified: boolean | null;
  source: string;
}

export interface CommitResponse {
  preview_id: string;
  operation: string;
  resource_type: string;
  result: WriteResult;
  audit: AuditEntry;
}

export interface ManagedOperation {
  id: string;
  label: string;
  destructive: boolean;
  /**
   * This verb takes no payload — running it is the whole request, so it can be
   * offered as a single button. `activate` a scene, `run` a script, `trigger`
   * an automation. A verb that needs a value (`set`, `rename`, `edit`) is
   * false, and so is one the backend has not classified.
   */
  valueless: boolean;
}

/**
 * Something an operation may target — a household member, a feature.
 *
 * `id` is the bridge's own token. It is never a Home Assistant entity id: the
 * bridge does not hand those out, and this app must not reconstruct one.
 */
export interface ManagedTarget {
  id: string;
  label: string;
  risk: string | null;
  /** Features only. `null` means unknown, which blocks a preview. */
  enabled: boolean | null;
}

export interface ManagementResource {
  id: string;
  label: string;
  available: boolean;
  operations: ManagedOperation[];
  targets: ManagedTarget[];
  detail: string | null;
}

export interface ManagementStatus {
  available: boolean;
  /** Hebrew. Shown when management is off. */
  reason: string | null;
  contract_version: string | null;
  resources: ManagementResource[];
  /**
   * Home Assistant's master write switch, as the bridge reports it. Off today:
   * previews work, commits are refused. Nothing in this app can turn it on.
   */
  writes_enabled: boolean;
  requires_preview: boolean;
  requires_confirmation: boolean;
  requires_read_after_write: boolean;
}

/** One task from the management snapshot. `uid` is the bridge's handle. */
export interface SnapshotTask {
  uid: string;
  summary: string;
  status: string;
  completed: boolean;
  due: string | null;
  owner_id: string;
  owner: string;
}

export interface TaskSnapshot {
  count: number;
  tasks: SnapshotTask[];
  owners: ManagedTarget[];
  writes_enabled: boolean;
}

export interface AuditLog {
  count: number;
  records: AuditEntry[];
}

// --- the contract-driven resources (3.0) -----------------------------------
// One shape for settings, users, Shabbat, rules, the calendar, devices and the
// system. The screens render from what the bridge described rather than from
// anything declared here, so a family Home Assistant has not shipped yet
// arrives as `available: false` with a reason and is shown as unavailable.

export interface ManagedOption {
  value: string;
  label: string;
  detail: string | null;
}

export interface ManagedConstraints {
  minimum: number | null;
  maximum: number | null;
  step: number | null;
  unit: string | null;
  max_length: number | null;
  allowed: ManagedOption[];
}

/** How an item is edited. Anything unrecognised is shown read-only. */
export type ItemKind =
  | 'toggle'
  | 'number'
  | 'time'
  | 'date'
  | 'datetime'
  | 'choice'
  | 'text'
  | 'list'
  /** A thing you run, not a value you set: it has no `value` and no read-back. */
  | 'action'
  | 'readonly';

/** `read_only` never gets a write control; `high` and `destructive` ask for a typed word. */
export type RiskLevel = 'read_only' | 'low' | 'medium' | 'high' | 'destructive';

export interface ManagedItem {
  id: string;
  label: string;
  group: string | null;
  kind: ItemKind | string;
  value: unknown;
  display: string | null;
  description: string | null;
  risk: RiskLevel | string;
  /** False unless the bridge said otherwise. No control is rendered without it. */
  controllable: boolean;
  operations: string[];
  /**
   * Which of `operations` sets the value this item reports, decided by the
   * backend. Under the live vocabulary one item carries several verbs — an air
   * conditioner accepts `power`, `temperature`, `fan_mode` — and taking the
   * first of them would send `power` for a temperature edit. `null` means
   * there is nothing to operate.
   */
  primary_operation: string | null;
  /**
   * The verbs on this item that are a whole request on their own and that the
   * control for its `kind` does not already send — a scene's `activate`, an
   * automation's `trigger`, a vacuum's `pause`. Worked out by the backend,
   * which is the side that knows a switch stands for `enable`, `disable`,
   * `set`, `power`, `start` and `stop` at once.
   */
  run_operations: string[];
  options: ManagedOption[];
  constraints: ManagedConstraints | null;
  unavailable_reason: string | null;
  /**
   * Canonical extras — a rule's days, an event's start, a device's class.
   * Never a raw Home Assistant entity id: the backend drops those, so there is
   * nothing here that could be used to name a service.
   */
  detail: Record<string, unknown>;
}

export interface ManagedGroup {
  id: string;
  label: string;
  description: string | null;
  items: ManagedItem[];
}

export interface ResourceSnapshot {
  resource: string;
  available: boolean;
  reason: string | null;
  writes_enabled: boolean;
  groups: ManagedGroup[];
  items: ManagedItem[];
  detail: Record<string, unknown>;
}

/** The families with a `/{resource}/snapshot` endpoint. */
export type ManagedResource =
  | 'lists'
  | 'settings'
  | 'users'
  | 'shabbat'
  | 'rules'
  | 'calendar'
  | 'devices'
  | 'helpers'
  | 'automations'
  | 'scripts'
  | 'scenes'
  | 'system';
