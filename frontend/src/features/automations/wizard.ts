/**
 * Wizard state for the automation editor.
 *
 * Which steps apply depends on the automation type, so the step list is derived
 * rather than fixed. The human-readable preview shown before saving comes from
 * the *backend*, not from here — this file only decides what the wizard asks.
 */

import type {
  Automation,
  AutomationDraft,
  AutomationTarget,
  AutomationType,
  Device,
} from '@/types/api';

export type StepId = 'action' | 'target' | 'time' | 'days' | 'conditions' | 'summary';

export const STEP_LABELS: Record<StepId, string> = {
  action: 'מה לעשות?',
  target: 'על מה?',
  time: 'מתי?',
  days: 'ימים',
  conditions: 'תנאים',
  summary: 'סיכום',
};

export const ACTION_OPTIONS = [
  { type: 'turn_on', label: 'להדליק' },
  { type: 'turn_off', label: 'לכבות' },
  { type: 'open', label: 'לפתוח' },
  { type: 'close', label: 'לסגור' },
  { type: 'notify', label: 'לשלוח הודעה' },
] as const;

export const TYPE_OPTIONS: Array<{ value: AutomationType; label: string; help: string }> = [
  { value: 'one_time', label: 'חד־פעמי', help: 'פעם אחת, בתאריך ושעה מסוימים.' },
  { value: 'daily', label: 'יומי', help: 'כל יום באותה שעה.' },
  { value: 'weekly', label: 'שבועי', help: 'בימים שתבחרו.' },
  { value: 'time_window', label: 'טווח שעות', help: 'להדליק בשעה אחת ולכבות בשנייה.' },
  { value: 'multi_time', label: 'כמה שעות', help: 'כמה זמנים ביום.' },
  { value: 'conditional', label: 'מותנה', help: 'רק אם מתקיים תנאי.' },
];

export function emptyDraft(): AutomationDraft {
  return {
    name: '',
    enabled: true,
    automation_type: 'weekly',
    targets: [],
    actions: [],
    days: [0, 1, 2, 3, 4],
    start_time: '19:00',
    end_time: null,
    times: [],
    conditions: [],
  };
}

export function draftFromAutomation(automation: Automation): AutomationDraft {
  return {
    id: automation.id,
    name: automation.name,
    enabled: automation.enabled,
    automation_type: automation.automation_type,
    targets: automation.targets,
    actions: automation.actions,
    days: automation.days,
    start_time: automation.start_time,
    end_time: automation.end_time,
    times: automation.times,
    run_date: automation.run_date,
    conditions: automation.conditions,
    owner: automation.owner,
  };
}

/** Days and conditions are only asked for when the type actually uses them. */
export function stepsFor(type: AutomationType): StepId[] {
  const steps: StepId[] = ['action', 'target', 'time'];
  if (type !== 'one_time' && type !== 'daily') steps.push('days');
  if (type === 'conditional') steps.push('conditions');
  steps.push('summary');
  return steps;
}

export function targetFromDevice(device: Device): AutomationTarget {
  return { id: device.id, name: device.display_name, room: device.room };
}

/**
 * Client-side gate for the "next" button. The backend validates again on
 * preview — this only avoids a pointless round trip.
 */
export function canAdvance(draft: AutomationDraft, step: StepId): boolean {
  switch (step) {
    case 'action':
      return draft.actions.length > 0 && draft.name.trim().length > 0;
    case 'target':
      return draft.targets.length > 0;
    case 'time':
      if (draft.automation_type === 'multi_time') return draft.times.length > 0;
      if (draft.automation_type === 'time_window') {
        return Boolean(draft.start_time) && Boolean(draft.end_time);
      }
      return Boolean(draft.start_time);
    case 'days':
      return draft.days.length > 0;
    case 'conditions':
      return true;
    case 'summary':
      return true;
    default:
      return true;
  }
}
