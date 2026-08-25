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

export interface BridgeStatus {
  ok: boolean | null;
  version: string | null;
  uptime: string | null;
  components: StatusComponent[];
  /** Numeric headline figures, rendered dynamically. */
  counts: Record<string, number>;
  /** Remaining scalar fields the bridge sent. */
  details: Record<string, string>;
  writes_enabled: boolean;
}

// --- devices ---------------------------------------------------------------
export interface DeviceLimits {
  min: number | null;
  max: number | null;
  step: number | null;
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
export interface ShabbatProfile {
  id: string;
  /** The bridge's own profile key, e.g. `pre_off`. */
  kind: string;
  label: string;
  active: boolean | null;
  time: string | null;
  offset_minutes: number | null;
  /** Friendly device names, already resolved from tokens by the backend. */
  devices: string[];
  extra: Extra;
}

export interface BridgeShabbat {
  candle_lighting: string | null;
  havdalah: string | null;
  parasha: string | null;
  pre_shabbat_offset_minutes: number | null;
  profiles: ShabbatProfile[];
  /** Friendly device name → temperature, already resolved. */
  ac_temperatures: Record<string, string>;
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
