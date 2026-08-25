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
};

export function countLabel(key: string): string {
  return COUNT_LABELS[key] ?? key.replace(/_/g, ' ');
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

export const SCHEDULE_KIND_LABELS: Record<string, string> = {
  one_time: 'חד־פעמי',
  daily: 'יומי',
  weekly: 'שבועי',
  immediate: 'מיידי',
  recurring: 'חוזר',
};

export function scheduleKindLabel(kind: string | null | undefined): string {
  if (!kind) return '—';
  return SCHEDULE_KIND_LABELS[kind] ?? kind;
}

/** Format a value from an open-ended bridge object for display. */
export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'כן' : 'לא';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
