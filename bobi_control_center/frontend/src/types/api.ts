/**
 * TypeScript mirror of the backend's Pydantic models.
 *
 * This is the single file allowed to mention Home Assistant vocabulary, and
 * only inside the `Advanced` block, which the UI may render but never branch on.
 */

export type Severity = 'ok' | 'warning' | 'error';
export type HealthState = 'online' | 'degraded' | 'offline' | 'unknown';
export type Source = 'web' | 'whatsapp' | 'automation' | 'system';

export type DeviceCategory =
  | 'light'
  | 'climate'
  | 'camera'
  | 'cover'
  | 'switch'
  | 'boiler'
  | 'vacuum'
  | 'sensor';

export type AutomationType =
  | 'one_time'
  | 'daily'
  | 'weekly'
  | 'time_window'
  | 'multi_time'
  | 'conditional'
  | 'smart_notification';

/** Technical detail. Display-only — never read by UI logic. */
export interface Advanced {
  entity_id: string | null;
  object_id: string | null;
  integration: string | null;
  notes: string[];
  raw: Record<string, unknown>;
}

// --- safety model ----------------------------------------------------------
export interface PreviewLine {
  text: string;
  emphasis: boolean;
}

export interface ChangePreview {
  summary: string;
  lines: PreviewLine[];
  warnings: string[];
  requires_confirmation: boolean;
  destructive: boolean;
  /** Opaque; must be echoed back on confirm. */
  token: string;
}

export interface OperationResult {
  success: boolean;
  message: string;
  dry_run: boolean;
  applied: boolean;
  audit_id: string | null;
}

// --- status ----------------------------------------------------------------
export interface ComponentHealth {
  id: string;
  name: string;
  state: HealthState;
  label: string;
  detail: string | null;
}

export interface StatItem {
  id: string;
  label: string;
  value: number;
  hint: string | null;
  severity: Severity;
}

export interface ActivityEntry {
  id: string;
  time: string;
  timestamp: string;
  title: string;
  detail: string | null;
  icon: string;
  severity: Severity;
}

export interface AttentionItem {
  id: string;
  title: string;
  description: string;
  severity: Severity;
  component: string | null;
  technical_details: string | null;
  action_label: string | null;
  action_href: string | null;
}

export interface SystemStatus {
  name: string;
  version: string;
  adapter: string;
  read_only: boolean;
  generated_at: string;
  components: ComponentHealth[];
  stats: StatItem[];
  activity: ActivityEntry[];
  attention: AttentionItem[];
}

// --- capabilities ----------------------------------------------------------
export interface CapabilitySetting {
  key: string;
  label: string;
  type: 'bool' | 'text' | 'select' | 'time_range' | 'number';
  value: unknown;
  options: string[];
  help: string | null;
}

export interface Capability {
  id: string;
  name: string;
  description: string;
  icon: string;
  group: string;
  enabled: boolean;
  state: HealthState;
  state_label: string;
  warning: string | null;
  settings: CapabilitySetting[];
  related_device_ids: string[];
  last_used: string | null;
  advanced: Advanced;
}

// --- devices ---------------------------------------------------------------
export interface Device {
  id: string;
  display_name: string;
  room: string;
  category: DeviceCategory;
  state: string;
  state_label: string;
  available: boolean;
  aliases: string[];
  capabilities: string[];
  icon: string;
  advanced: Advanced;
}

export interface DeviceList {
  devices: Device[];
  rooms: string[];
  categories: DeviceCategory[];
}

// --- automations -----------------------------------------------------------
export interface AutomationTarget {
  id: string;
  name: string;
  room: string | null;
}

export interface AutomationAction {
  type: string;
  label: string;
  value: unknown;
}

export interface AutomationCondition {
  type: string;
  label: string;
  operator: string | null;
  value: unknown;
}

export interface Automation {
  id: string;
  name: string;
  enabled: boolean;
  automation_type: AutomationType;
  targets: AutomationTarget[];
  actions: AutomationAction[];
  days: number[];
  start_time: string | null;
  end_time: string | null;
  times: string[];
  run_date: string | null;
  conditions: AutomationCondition[];
  owner: string | null;
  created_by: string | null;
  source: Source;
  last_triggered: string | null;
  crosses_midnight: boolean;
  summary: string;
  advanced: Advanced;
}

export interface AutomationDraft {
  id?: string | null;
  name: string;
  enabled: boolean;
  automation_type: AutomationType;
  targets: AutomationTarget[];
  actions: AutomationAction[];
  days: number[];
  start_time: string | null;
  end_time: string | null;
  times: string[];
  run_date?: string | null;
  conditions: AutomationCondition[];
  owner?: string | null;
}

export interface AutomationList {
  automations: Automation[];
}

// --- shabbat ---------------------------------------------------------------
export type ShabbatDay = 'friday' | 'saturday';

export interface TimeRange {
  id: string;
  start: string;
  end: string;
  /** Computed by the backend — never re-derived in the UI. */
  crosses_midnight: boolean;
  enabled: boolean;
  day: ShabbatDay;
}

export interface ShabbatDeviceSchedule {
  id: string;
  device_id: string;
  device_name: string;
  room: string;
  icon: string;
  enabled: boolean;
  ranges: TimeRange[];
  note: string | null;
  advanced: Advanced;
}

export interface ShabbatTemplate {
  id: string;
  name: string;
  description: string;
  created_at: string;
  schedules: ShabbatDeviceSchedule[];
}

export interface ShabbatTimes {
  parasha: string;
  candle_lighting: string;
  havdalah: string;
  friday_date: string;
  saturday_date: string;
  city: string;
}

export interface ShabbatConfig {
  enabled: boolean;
  times: ShabbatTimes;
  schedules: ShabbatDeviceSchedule[];
  templates: ShabbatTemplate[];
  active_template_id: string | null;
  updated_at: string | null;
  has_draft: boolean;
}

export interface ShabbatDraft {
  enabled: boolean;
  schedules: ShabbatDeviceSchedule[];
  active_template_id: string | null;
}

// --- notifications ---------------------------------------------------------
export interface QuietHours {
  enabled: boolean;
  start: string;
  end: string;
  behavior: 'hold' | 'drop' | 'send';
}

export interface NotificationCondition {
  label: string;
  detail: string | null;
}

export interface NotificationRule {
  id: string;
  name: string;
  description: string;
  icon: string;
  enabled: boolean;
  recipients: string[];
  lead_time_minutes: number | null;
  quiet_hours: QuietHours;
  conditions: NotificationCondition[];
  frequency: string;
  cooldown_minutes: number;
  last_triggered: string | null;
  trigger_count_7d: number;
  advanced: Advanced;
}

export interface NotificationList {
  rules: NotificationRule[];
}

// --- users -----------------------------------------------------------------
export type Permission =
  | 'control_devices'
  | 'manage_automations'
  | 'manage_shabbat'
  | 'manage_tasks'
  | 'manage_calendar'
  | 'view_cameras'
  | 'manage_bobi';

export interface NotificationPreferences {
  whatsapp: boolean;
  push: boolean;
  summary_daily: boolean;
  urgent_only: boolean;
}

export interface User {
  id: string;
  name: string;
  enabled: boolean;
  role: string;
  role_label: string;
  avatar_color: string;
  whatsapp_connected: boolean;
  whatsapp_hint: string;
  calendar: string | null;
  task_list: string | null;
  permissions: Permission[];
  notification_preferences: NotificationPreferences;
  quiet_hours: QuietHours;
}

export interface PermissionInfo {
  id: Permission;
  label: string;
  description: string;
}

export interface UserList {
  users: User[];
  permissions: PermissionInfo[];
}

// --- tasks & calendar ------------------------------------------------------
export interface Task {
  id: string;
  title: string;
  owner: string;
  completed: boolean;
  due: string | null;
  due_label: string | null;
  list_name: string;
  created_by: string;
  advanced: Advanced;
}

export interface CalendarEvent {
  id: string;
  title: string;
  owner: string;
  start: string;
  end: string | null;
  day_label: string;
  time_label: string;
  location: string | null;
  all_day: boolean;
  bobi_features: string[];
  advanced: Advanced;
}

export interface TaskList {
  open_tasks: Task[];
  completed_tasks: Task[];
}

export interface CalendarList {
  events: CalendarEvent[];
}

// --- probe -----------------------------------------------------------------
export type ProbeFamily =
  | 'schedule'
  | 'control'
  | 'query'
  | 'task'
  | 'calendar'
  | 'notification'
  | 'shabbat'
  | 'unknown';

export interface ProbeTarget {
  id: string | null;
  name: string | null;
  room: string | null;
  matched_alias: string | null;
  confidence: number;
}

export interface ProbeSchedule {
  kind: string;
  time: string | null;
  date: string | null;
  days: number[];
  description: string;
}

export interface ProbeStep {
  id: string;
  label: string;
  status: 'ok' | 'warning' | 'skipped' | 'failed';
  value: string | null;
  detail: string | null;
}

export interface ProbeResult {
  original_text: string;
  normalized_text: string;
  family: ProbeFamily;
  domain: string | null;
  action: string | null;
  target: ProbeTarget;
  schedule: ProbeSchedule | null;
  skill: string | null;
  safe: boolean;
  /** Always false. The probe endpoint cannot execute. */
  would_execute: boolean;
  warnings: string[];
  steps: ProbeStep[];
  confidence: number;
  duration_ms: number;
}

export interface ProbeHistoryEntry {
  id: string;
  text: string;
  family: ProbeFamily;
  summary: string;
  timestamp: string;
  safe: boolean;
}

export interface ProbeHistory {
  entries: ProbeHistoryEntry[];
}

// --- diagnostics, tests, audit, settings -----------------------------------
export interface DiagnosticIssue {
  id: string;
  severity: Severity;
  title: string;
  description: string;
  component: string;
  first_seen: string;
  last_seen: string;
  occurrences: number;
  suggested_action: string | null;
  technical_details: string | null;
}

export interface DiagnosticsReport {
  issues: DiagnosticIssue[];
  ok_count: number;
  warning_count: number;
  error_count: number;
  generated_at: string;
}

export interface TestCase {
  id: string;
  name: string;
  passed: boolean;
  duration_ms: number;
  message: string | null;
}

export interface TestSuite {
  id: string;
  name: string;
  description: string;
  total: number;
  passed: number;
  failed: number;
  duration_ms: number;
  last_run: string | null;
  cases: TestCase[];
}

export interface TestReport {
  suites: TestSuite[];
  total: number;
  passed: number;
  failed: number;
  last_run: string | null;
  running: boolean;
  note: string;
}

export interface AuditEntry {
  id: string;
  timestamp: string;
  user: string;
  operation: string;
  operation_label: string;
  resource_type: string;
  resource_id: string;
  resource_label: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  success: boolean;
  source: Source;
}

export interface AuditLog {
  entries: AuditEntry[];
  total: number;
}

export interface SettingField {
  key: string;
  label: string;
  type: 'text' | 'bool' | 'select' | 'time' | 'info' | 'secret';
  value: unknown;
  options: string[];
  help: string | null;
  secret: boolean;
  editable: boolean;
}

export interface SettingsSection {
  id: string;
  title: string;
  description: string;
  icon: string;
  fields: SettingField[];
}

export interface SettingsResponse {
  sections: SettingsSection[];
  read_only: boolean;
  note: string;
}

/** The backend's structured error envelope. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}
