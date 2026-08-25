/** Hebrew display formatting for bridge values. */

/** Relative time in Hebrew, e.g. "לפני 5 דקות". */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return 'מעולם לא';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';

  const minutes = Math.round((Date.now() - then) / 60_000);
  if (minutes < 0) return 'עוד מעט';
  if (minutes < 1) return 'הרגע';
  if (minutes < 60) return `לפני ${minutes} דקות`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? 'לפני שעה' : `לפני ${hours} שעות`;

  const days = Math.round(hours / 24);
  if (days === 1) return 'אתמול';
  if (days < 30) return `לפני ${days} ימים`;

  const months = Math.round(days / 30);
  return months === 1 ? 'לפני חודש' : `לפני ${months} חודשים`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('he-IL', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('he-IL', { day: 'numeric', month: 'long' }).format(date);
}

/** Human label for a device or entity state coming from Home Assistant. */
const STATE_LABELS: Record<string, string> = {
  on: 'דולק',
  off: 'כבוי',
  open: 'פתוח',
  closed: 'סגור',
  cool: 'מקרר',
  heat: 'מחמם',
  fan_only: 'מאוורר',
  dry: 'מייבש',
  auto: 'אוטומטי',
  docked: 'בעמדת טעינה',
  cleaning: 'מנקה',
  returning: 'חוזר לעמדה',
  recording: 'מקליט',
  streaming: 'משדר',
  idle: 'ממתין',
  home: 'בבית',
  not_home: 'לא בבית',
  unavailable: 'לא זמין',
  unknown: 'לא ידוע',
};

export function stateLabel(state: string | null | undefined): string {
  if (!state) return 'לא ידוע';
  const known = STATE_LABELS[state.toLowerCase()];
  if (known) return known;
  // Numeric sensor readings pass through unchanged.
  return state;
}

export function isAvailable(state: string | null | undefined): boolean {
  const value = (state ?? '').toLowerCase();
  return value !== '' && value !== 'unavailable' && value !== 'unknown';
}

/** The user-facing name of a device. Never the entity id. */
export function deviceName(device: {
  canonical?: string | null;
  name?: string | null;
  entity_id?: string | null;
}): string {
  return device.canonical || device.name || device.entity_id || 'מכשיר ללא שם';
}

export const SCOPE_LABELS: Record<string, string> = {
  all: 'הכול',
  lighting: 'תאורה',
  climate: 'מיזוג',
  cameras: 'מצלמות',
  battery: 'סוללות',
  temperature: 'טמפרטורה',
  humidity: 'לחות',
  vacuum: 'שואב',
  people: 'אנשים',
  switches: 'שקעים',
  scent: 'ריח',
};

export const RISK_LABELS: Record<string, string> = {
  low: 'סיכון נמוך',
  medium: 'סיכון בינוני',
  high: 'סיכון גבוה',
};

export const RISK_TONE: Record<string, 'ok' | 'warning' | 'error' | 'muted'> = {
  low: 'ok',
  medium: 'warning',
  high: 'error',
};

/** Statistic labels for the dashboard's `counts` map. */
export const COUNT_LABELS: Record<string, string> = {
  devices: 'מכשירים',
  capabilities: 'יכולות',
  rules: 'כללים חכמים',
  open_tasks: 'משימות פתוחות',
  tasks: 'משימות',
  issues: 'בעיות פתוחות',
  automations: 'אוטומציות',
  schedules: 'תזמונים',
  users: 'משתמשים',
  // Counters the real bridge sends.
  catalog_count: 'מכשירים בקטלוג',
  catalog_controllable: 'ניתנים לשליטה',
  rules_count: 'כללים חכמים',
  issue_count: 'בעיות פתוחות',
  users_count: 'משתמשים',
};

export function countLabel(key: string): string {
  return COUNT_LABELS[key] ?? key.replace(/_/g, ' ');
}

/**
 * Device limit labels.
 *
 * The backend keeps every domain-specific limit the bridge sends, so the
 * Advanced panel can name them instead of printing snake_case keys.
 */
export const LIMIT_LABELS: Record<string, string> = {
  min_temp: 'טמפרטורה מינימלית',
  max_temp: 'טמפרטורה מקסימלית',
  temp_step: 'קפיצת טמפרטורה',
  hvac_modes: 'מצבי הפעלה',
  preset_modes: 'מצבים מוגדרים',
  fan_modes: 'עוצמות מאוורר',
  swing_modes: 'מצבי הפניית אוויר',
  min_kelvin: 'גוון חם ביותר (K)',
  max_kelvin: 'גוון קר ביותר (K)',
  min_brightness: 'בהירות מינימלית',
  max_brightness: 'בהירות מקסימלית',
  intensity_min: 'עוצמה מינימלית',
  intensity_max: 'עוצמה מקסימלית',
  scent_slots: 'תאי ריח',
  timer_max_seconds: 'טיימר מקסימלי (שניות)',
  min: 'מינימום',
  max: 'מקסימום',
  step: 'קפיצה',
};

export function limitLabel(key: string): string {
  return LIMIT_LABELS[key] ?? key.replace(/_/g, ' ');
}

/**
 * The limits worth showing, in reading order, skipping empty ones.
 *
 * `min`/`max`/`step` are the backend's generic view of whichever domain range
 * applies, so they are left out when the domain fields themselves are present —
 * showing both would just repeat the same numbers.
 */
export function limitEntries(
  limits: Record<string, unknown> | null | undefined,
): Array<[string, string]> {
  if (!limits) return [];
  const domainKeys = Object.keys(LIMIT_LABELS).filter(
    (key) => key !== 'min' && key !== 'max' && key !== 'step',
  );
  const hasDomainValue = domainKeys.some((key) => !isEmptyLimit(limits[key]));
  const keys = hasDomainValue ? domainKeys : ['min', 'max', 'step'];

  return keys
    .filter((key) => !isEmptyLimit(limits[key]))
    .map((key) => [limitLabel(key), formatLimit(limits[key])] as [string, string]);
}

function isEmptyLimit(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  return Array.isArray(value) && value.length === 0;
}

function formatLimit(value: unknown): string {
  return Array.isArray(value) ? value.join(' · ') : displayValue(value);
}

/** Probe status → Hebrew. Unknown statuses fall through readably. */
export const PROBE_STATUS_LABELS: Record<string, string> = {
  ok: 'הובן',
  not_understood: 'לא הובן',
  target_not_found: 'לא נמצא יעד',
  invalid_schedule: 'תזמון לא תקין',
  error: 'שגיאה',
};

export function probeStatusLabel(status: string | null | undefined): string {
  if (!status) return 'לא ידוע';
  return PROBE_STATUS_LABELS[status] ?? status;
}

/**
 * Schedule kinds Bobi's dispatcher returns.
 *
 * `next_night_clock` is one the real bridge sends: a clock time in the small
 * hours, which Bobi resolves to the coming night rather than today.
 */
export const SCHEDULE_KIND_LABELS: Record<string, string> = {
  one_time: 'חד־פעמי',
  next_night_clock: 'הלילה הקרוב',
  next_day_clock: 'מחר',
  today_clock: 'היום',
  daily: 'יומי',
  weekly: 'שבועי',
  immediate: 'מיידי',
  recurring: 'חוזר',
  relative: 'יחסי',
};

export function scheduleKindLabel(kind: string | null | undefined): string {
  if (!kind) return '—';
  // An unrecognised kind is still a machine token, so at least soften it
  // rather than showing snake_case to a household member.
  return SCHEDULE_KIND_LABELS[kind] ?? kind.replace(/_/g, ' ');
}

/** Format a value from an open-ended bridge object for display. */
export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'כן' : 'לא';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
