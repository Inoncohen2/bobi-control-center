/**
 * TypeScript mirror of the backend's bridge models.
 *
 * These shapes come from Bobi's `script.bobi_cc_*` services. Two properties
 * carry through from the backend and matter when rendering:
 *
 * - **Almost everything is optional.** A partial bridge response must still
 *   produce a usable screen, so every component treats missing values as
 *   "unknown" rather than assuming they exist.
 * - **Unknown fields are preserved.** The registry grows independently of this
 *   app, so extra keys are rendered in the Advanced panel rather than dropped.
 *
 * `entity_id` and `handler` are technical: display them only inside the
 * "מתקדם / פרטים טכניים" disclosure.
 */

/** Any bridge object may carry keys this app does not know about. */
export type Extras = Record<string, unknown>;

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
export interface StatusComponent extends Extras {
  id: string | null;
  name: string | null;
  state: string | null;
  label: string | null;
  detail: string | null;
  ok: boolean | null;
}

export interface BridgeStatus extends Extras {
  ok: boolean | null;
  version: string | null;
  uptime: string | null;
  components: StatusComponent[];
  counts: Record<string, number>;
  writes_enabled: boolean;
}

// --- devices ---------------------------------------------------------------
export interface DeviceLimits extends Extras {
  min: number | null;
  max: number | null;
  step: number | null;
}

export interface BridgeDevice extends Extras {
  entity_id: string | null;
  name: string | null;
  /** The human-facing name. Preferred over `name` everywhere in the UI. */
  canonical: string | null;
  semantic_scopes: string[];
  aliases: string[];
  domain: string | null;
  group: string | null;
  area: string | null;
  state: string | null;
  controllable: boolean | null;
  logical_controllable: boolean | null;
  handler: string | null;
  capabilities: string[];
  limits: DeviceLimits | null;
  last_changed: string | null;
}

export interface BridgeDevices extends Extras {
  scope: string | null;
  include_unavailable: boolean | null;
  count: number | null;
  devices: BridgeDevice[];
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
export interface BridgeCapability extends Extras {
  id: string | null;
  handler: string | null;
  local: boolean | null;
  local_after_parse: boolean | null;
  risk: string | null;
  label: string | null;
  example: string | null;
  group: string | null;
}

/** A runtime master switch. READ-ONLY in Phase 2. */
export interface CapabilityToggle extends Extras {
  id: string | null;
  name: string | null;
  label: string | null;
  state: string | null;
  enabled: boolean | null;
  entity_id: string | null;
}

export interface BridgeCapabilities extends Extras {
  count: number | null;
  capabilities: BridgeCapability[];
  toggles: CapabilityToggle[];
}

// --- users -----------------------------------------------------------------
export interface BridgeUser extends Extras {
  id: string | null;
  name: string | null;
  role: string | null;
  enabled: boolean | null;
  whatsapp_connected: boolean | null;
  calendar: string | null;
  task_list: string | null;
  permissions: string[];
  areas: string[];
}

export interface BridgeUsers extends Extras {
  count: number | null;
  users: BridgeUser[];
}

// --- probe -----------------------------------------------------------------
export interface ProbeUnderstanding extends Extras {
  intent: string | null;
  action: string | null;
  domain: string | null;
  target: string | null;
  targets: string[];
  area: string | null;
  value: unknown;
  time: string | null;
  date: string | null;
}

export interface BridgeProbe extends Extras {
  handled: boolean | null;
  status: string | null;
  terminal: boolean | null;
  skill: string | null;
  understanding: ProbeUnderstanding | null;
  schedule_valid: boolean | null;
  schedule_reason: string | null;
  schedule_kind: string | null;
  text: string | null;
  error: string | null;
  /** Invariants of the Phase 2 contract. Always true / false respectively. */
  probe_only: boolean;
  would_execute: boolean;
}

// --- shabbat ---------------------------------------------------------------
export interface ShabbatProfile extends Extras {
  id: string | null;
  name: string | null;
  label: string | null;
  active: boolean | null;
  devices: string[];
  time: string | null;
  offset_minutes: number | null;
}

export interface BridgeShabbat extends Extras {
  candle_lighting: string | null;
  havdalah: string | null;
  pre_shabbat_offset_minutes: number | null;
  pre_off_profile: ShabbatProfile | null;
  pre_on_profile: ShabbatProfile | null;
  night_off_profile: ShabbatProfile | null;
  morning_on_profile: ShabbatProfile | null;
  ac_temperatures: Record<string, unknown>;
  /** device token → friendly label, so a raw token is never shown. */
  device_labels: Record<string, string>;
  has_draft: boolean | null;
  /** False for the whole of Phase 2. */
  writes_enabled: boolean;
}

// --- rules -----------------------------------------------------------------
export interface BridgeRule extends Extras {
  id: string | null;
  name: string | null;
  label: string | null;
  description: string | null;
  enabled: boolean | null;
  kind: string | null;
  trigger: string | null;
  schedule: string | null;
  targets: string[];
  last_triggered: string | null;
  entity_id: string | null;
}

export interface BridgeRules extends Extras {
  count: number | null;
  rules: BridgeRule[];
}

// --- tasks -----------------------------------------------------------------
export interface BridgeTask extends Extras {
  id: string | null;
  title: string | null;
  summary: string | null;
  status: string | null;
  completed: boolean | null;
  due: string | null;
  owner: string | null;
  list_name: string | null;
}

export interface BridgeTasks extends Extras {
  count: number | null;
  tasks: BridgeTask[];
}

// --- diagnostics -----------------------------------------------------------
export interface DiagnosticCheck extends Extras {
  id: string | null;
  name: string | null;
  label: string | null;
  ok: boolean | null;
  detail: string | null;
}

export interface BridgeIssue extends Extras {
  id: string | null;
  severity: string | null;
  title: string | null;
  label: string | null;
  message: string | null;
  description: string | null;
  component: string | null;
  entity_id: string | null;
  entity_ids: string[];
  suggested_action: string | null;
  detail: string | null;
}

export interface BridgeDiagnostics extends Extras {
  ok: boolean | null;
  issue_count: number | null;
  issues: BridgeIssue[];
  checks: DiagnosticCheck[];
}

/** The backend's structured error envelope. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}
