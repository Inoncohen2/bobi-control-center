/**
 * Hebrew display formatting.
 *
 * Anything derived from domain rules (does a window cross midnight, what does an
 * automation do) is computed by the backend. This file only formats values for
 * display.
 */

import type { DeviceCategory, Severity } from '@/types/api';

/** 0 = Sunday, matching the Hebrew week used across the app. */
export const HEBREW_DAYS = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'] as const;
export const HEBREW_DAYS_SHORT = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'] as const;

export function formatDays(days: number[]): string {
  if (days.length === 0) return '';
  const sorted = [...days].sort((a, b) => a - b);
  if (sorted.length === 7) return 'כל יום';
  if (sorted.join() === '0,1,2,3,4') return 'ראשון–חמישי';
  if (sorted.join() === '5,6') return 'סוף שבוע';

  const names = sorted.map((day) => HEBREW_DAYS[day] ?? '').filter(Boolean);
  if (names.length === 1) return names[0] as string;
  return `${names.slice(0, -1).join(', ')} ו${names[names.length - 1]}`;
}

/** Relative time in Hebrew, e.g. "לפני 5 דקות". */
export function timeAgo(iso: string | null): string {
  if (!iso) return 'מעולם לא';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';

  const minutes = Math.round((Date.now() - then) / 60_000);
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

export function formatDateTime(iso: string | null): string {
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

export function formatTime(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' }).format(date);
}

export const CATEGORY_LABELS: Record<DeviceCategory, string> = {
  light: 'תאורה',
  climate: 'מזגן',
  camera: 'מצלמה',
  cover: 'תריס',
  switch: 'שקע',
  boiler: 'דוד',
  vacuum: 'שואב',
  sensor: 'חיישן',
};

export const SEVERITY_LABELS: Record<Severity, string> = {
  ok: 'תקין',
  warning: 'אזהרה',
  error: 'שגיאה',
};

export const AUTOMATION_TYPE_LABELS: Record<string, string> = {
  one_time: 'חד־פעמי',
  daily: 'יומי',
  weekly: 'שבועי',
  time_window: 'טווח שעות',
  multi_time: 'כמה שעות',
  conditional: 'מותנה',
  smart_notification: 'התראה חכמה',
};

export const SOURCE_LABELS: Record<string, string> = {
  web: 'ממשק ניהול',
  whatsapp: 'WhatsApp',
  automation: 'אוטומציה',
  system: 'מערכת',
};

export const PROBE_FAMILY_LABELS: Record<string, string> = {
  schedule: 'תזמון',
  control: 'שליטה',
  query: 'שאלה',
  task: 'משימה',
  calendar: 'יומן',
  notification: 'התראה',
  shabbat: 'שעון שבת',
  unknown: 'לא זוהה',
};

export const SHABBAT_DAY_LABELS: Record<string, string> = {
  friday: 'שישי',
  saturday: 'שבת',
};

/** "3 שעות ו-30 דקות" for a cooldown or lead time given in minutes. */
export function formatMinutes(minutes: number): string {
  if (minutes <= 0) return 'ללא';
  if (minutes < 60) return `${minutes} דקות`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const hoursLabel = hours === 1 ? 'שעה' : `${hours} שעות`;
  return rest ? `${hoursLabel} ו-${rest} דקות` : hoursLabel;
}
