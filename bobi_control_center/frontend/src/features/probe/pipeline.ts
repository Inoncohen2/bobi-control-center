/**
 * Turn a bridge probe response into the visual pipeline the Test Center draws.
 *
 * The bridge returns a flat result (`handled`, `status`, `skill`,
 * `understanding`, `schedule_*`); this derives the discrete, inspectable stages
 * from it. Kept as a pure function so every branch is testable without React.
 */

import type { BridgeProbe } from '@/types/api';
import { displayValue, probeStatusLabel, scheduleKindLabel } from '@/utils/format';

/** Read an open-map value as display text, or undefined when unusable. */
function asText(value: unknown): string | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  if (typeof value === 'object') return undefined;
  return String(value);
}

export type StepStatus = 'ok' | 'warning' | 'skipped' | 'failed';

export interface PipelineStep {
  id: string;
  label: string;
  status: StepStatus;
  value: string;
  detail?: string;
}

const STATUS_TEXT: Record<StepStatus, string> = {
  ok: 'תקין',
  warning: 'אזהרה',
  skipped: 'לא רלוונטי',
  failed: 'נכשל',
};

export function stepStatusLabel(status: StepStatus): string {
  return STATUS_TEXT[status];
}

export function buildPipeline(result: BridgeProbe, originalText: string): PipelineStep[] {
  // Normalized server-side: always an object, never null.
  const understanding = result.understanding;
  const handled = result.handled === true;

  const steps: PipelineStep[] = [
    {
      id: 'text',
      label: 'טקסט',
      status: 'ok',
      value: result.text ?? originalText,
    },
    {
      id: 'understanding',
      label: 'הבנה',
      status: handled ? 'ok' : 'failed',
      value: probeStatusLabel(result.status),
      detail: asText(understanding.intent) ?? asText(understanding.action),
    },
  ];

  // Target: only meaningful once something was understood.
  const targets = understanding.targets;
  const target =
    asText(understanding.target) ??
    (Array.isArray(targets) && targets.length > 0 ? targets.map(String).join(', ') : null);

  steps.push({
    id: 'target',
    label: 'יעד',
    status: target ? 'ok' : handled ? 'skipped' : 'warning',
    value: target ?? 'לא זוהה',
    detail: asText(understanding.area),
  });

  // Schedule: three distinct outcomes — valid, invalid, or not part of the request.
  if (result.schedule_valid === true) {
    steps.push({
      id: 'schedule',
      label: 'תזמון',
      status: 'ok',
      value: scheduleKindLabel(result.schedule_kind),
      detail: result.schedule_reason ?? asText(understanding.time),
    });
  } else if (result.schedule_valid === false) {
    steps.push({
      id: 'schedule',
      label: 'תזמון',
      status: 'failed',
      value: 'תזמון לא תקין',
      detail: result.schedule_reason ?? undefined,
    });
  } else {
    steps.push({
      id: 'schedule',
      label: 'תזמון',
      status: 'skipped',
      value: scheduleKindLabel(result.schedule_kind),
      detail: result.schedule_reason ?? 'אין רכיב תזמון בבקשה',
    });
  }

  steps.push({
    id: 'skill',
    label: 'Skill',
    status: result.skill ? 'ok' : 'skipped',
    value: result.skill ?? 'לא נבחר',
    detail: result.terminal === true ? 'סופי' : result.terminal === false ? 'לא סופי' : undefined,
  });

  steps.push({
    id: 'safety',
    label: 'בדיקת בטיחות',
    status: 'ok',
    value: 'בדיקה בלבד',
    // The invariant, restated at the end of every pipeline.
    detail: 'לא בוצעה שום פעולה',
  });

  return steps;
}

/** Rows for the "מה בובי הבין" table. Skips empty values. */
export function understandingRows(result: BridgeProbe): Array<[string, string]> {
  const understanding = result.understanding;

  const labels: Record<string, string> = {
    intent: 'כוונה',
    action: 'פעולה',
    domain: 'תחום',
    target: 'יעד',
    targets: 'יעדים',
    area: 'חדר',
    value: 'ערך',
    time: 'שעה',
    date: 'תאריך',
  };

  return Object.entries(understanding)
    .filter(([, value]) => {
      if (value === null || value === undefined || value === '') return false;
      if (Array.isArray(value) && value.length === 0) return false;
      return true;
    })
    .map(([key, value]) => [labels[key] ?? key, displayValue(value)]);
}
