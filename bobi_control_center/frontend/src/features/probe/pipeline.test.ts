import { describe, expect, it } from 'vitest';

import { makeProbe } from '@/test/fixtures';
import { buildPipeline, understandingRows } from './pipeline';

const TEXT = 'כבה מזגן הורים ב-1:30 בלילה';

describe('buildPipeline', () => {
  it('always ends with the safety stage stating nothing ran', () => {
    const steps = buildPipeline(makeProbe(), TEXT);
    const last = steps[steps.length - 1];

    expect(last?.id).toBe('safety');
    expect(last?.value).toBe('בדיקה בלבד');
    expect(last?.detail).toBe('לא בוצעה שום פעולה');
  });

  it('renders the stages in order', () => {
    const steps = buildPipeline(makeProbe(), TEXT);
    expect(steps.map((step) => step.id)).toEqual([
      'text',
      'understanding',
      'target',
      'schedule',
      'skill',
      'safety',
    ]);
  });

  it('marks understanding failed when the bridge did not handle the text', () => {
    const steps = buildPipeline(makeProbe({ handled: false, status: 'not_understood' }), TEXT);
    const understanding = steps.find((step) => step.id === 'understanding');

    expect(understanding?.status).toBe('failed');
    expect(understanding?.value).toBe('לא הובן');
  });

  it('marks a valid schedule with its kind and reason', () => {
    const steps = buildPipeline(makeProbe(), TEXT);
    const schedule = steps.find((step) => step.id === 'schedule');

    expect(schedule?.status).toBe('ok');
    expect(schedule?.value).toBe('חד־פעמי');
    expect(schedule?.detail).toBe('תוזמן ל-01:30');
  });

  it('marks an invalid schedule as failed and shows why', () => {
    const steps = buildPipeline(
      makeProbe({ schedule_valid: false, schedule_reason: 'שעה לא תקינה' }),
      TEXT,
    );
    const schedule = steps.find((step) => step.id === 'schedule');

    expect(schedule?.status).toBe('failed');
    expect(schedule?.detail).toBe('שעה לא תקינה');
  });

  it('skips the schedule stage when the request has no timing', () => {
    const steps = buildPipeline(
      makeProbe({ schedule_valid: null, schedule_kind: 'immediate', schedule_reason: null }),
      TEXT,
    );
    const schedule = steps.find((step) => step.id === 'schedule');

    expect(schedule?.status).toBe('skipped');
    expect(schedule?.value).toBe('מיידי');
  });

  it('warns when nothing was understood and no target resolved', () => {
    const steps = buildPipeline(
      makeProbe({ handled: false, understanding: null }),
      TEXT,
    );
    const target = steps.find((step) => step.id === 'target');

    expect(target?.status).toBe('warning');
    expect(target?.value).toBe('לא זוהה');
  });

  it('falls back to the submitted text when the bridge echoes none', () => {
    const steps = buildPipeline(makeProbe({ text: null }), TEXT);
    expect(steps[0]?.value).toBe(TEXT);
  });

  it('joins multiple targets', () => {
    const steps = buildPipeline(
      makeProbe({
        understanding: {
          intent: 'device_control',
          action: 'turn_off',
          domain: null,
          target: null,
          targets: ['מזגן סלון', 'מזגן הורים'],
          area: null,
          value: null,
          time: null,
          date: null,
        },
      }),
      TEXT,
    );
    expect(steps.find((step) => step.id === 'target')?.value).toBe('מזגן סלון, מזגן הורים');
  });
});

describe('understandingRows', () => {
  it('labels the fields in Hebrew and skips empties', () => {
    const rows = understandingRows(makeProbe());
    const labels = rows.map(([label]) => label);

    expect(labels).toContain('כוונה');
    expect(labels).toContain('יעד');
    expect(labels).toContain('שעה');
    // `targets: []` and null values are omitted.
    expect(labels).not.toContain('יעדים');
    expect(labels).not.toContain('תאריך');
  });

  it('returns nothing when the bridge sent no understanding', () => {
    expect(understandingRows(makeProbe({ understanding: null }))).toEqual([]);
  });
});
