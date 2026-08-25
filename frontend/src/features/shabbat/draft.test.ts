import { describe, expect, it } from 'vitest';

import { makeRange, makeShabbatConfig } from '@/test/fixtures';
import {
  countActiveRanges,
  draftReducer,
  localCrossesMidnight,
  toDraft,
  type DraftState,
} from './draft';

const config = makeShabbatConfig();
const initial: DraftState = { schedules: structuredClone(config.schedules), dirty: false };

describe('localCrossesMidnight', () => {
  it.each([
    ['17:42', '23:30', false],
    ['22:00', '01:00', true],
    ['18:00', '00:30', true],
    ['00:15', '06:00', false],
    ['23:59', '00:01', true],
  ])('%s → %s crosses midnight: %s', (start, end, expected) => {
    expect(localCrossesMidnight(start, end)).toBe(expected);
  });
});

describe('draftReducer', () => {
  it('starts clean and becomes dirty on the first edit', () => {
    expect(initial.dirty).toBe(false);
    const next = draftReducer(initial, {
      type: 'toggleSchedule',
      scheduleId: 'sch_kitchen_light',
    });
    expect(next.dirty).toBe(true);
  });

  it('toggles one schedule without touching the others', () => {
    const next = draftReducer(initial, {
      type: 'toggleSchedule',
      scheduleId: 'sch_kitchen_light',
    });
    expect(next.schedules[0]?.enabled).toBe(false);
    expect(next.schedules[1]?.enabled).toBe(true);
  });

  it('recomputes the cross-midnight flag when an end time is edited', () => {
    const next = draftReducer(initial, {
      type: 'setRangeTime',
      scheduleId: 'sch_kitchen_light',
      rangeId: 'r1',
      field: 'end',
      value: '01:00',
    });
    const range = next.schedules[0]?.ranges[0];
    expect(range?.end).toBe('01:00');
    expect(range?.crosses_midnight).toBe(true);
  });

  it('clears the flag when the range no longer crosses midnight', () => {
    const next = draftReducer(initial, {
      type: 'setRangeTime',
      scheduleId: 'sch_living_room_ac',
      rangeId: 'r2',
      field: 'end',
      value: '23:00',
    });
    expect(next.schedules[1]?.ranges[0]?.crosses_midnight).toBe(false);
  });

  it('adds and removes ranges', () => {
    const added = draftReducer(initial, {
      type: 'addRange',
      scheduleId: 'sch_kitchen_light',
      day: 'saturday',
    });
    expect(added.schedules[0]?.ranges).toHaveLength(2);
    expect(added.schedules[0]?.ranges[1]?.day).toBe('saturday');

    const removed = draftReducer(added, {
      type: 'removeRange',
      scheduleId: 'sch_kitchen_light',
      rangeId: 'r1',
    });
    expect(removed.schedules[0]?.ranges).toHaveLength(1);
  });

  it('reset discards edits and clears the dirty flag', () => {
    const edited = draftReducer(initial, {
      type: 'setRangeTime',
      scheduleId: 'sch_kitchen_light',
      rangeId: 'r1',
      field: 'end',
      value: '01:00',
    });
    const reset = draftReducer(edited, { type: 'reset', schedules: config.schedules });
    expect(reset.dirty).toBe(false);
    expect(reset.schedules[0]?.ranges[0]?.end).toBe('23:30');
  });

  it('reset deep-copies so later edits cannot mutate the source', () => {
    const reset = draftReducer(initial, { type: 'reset', schedules: config.schedules });
    draftReducer(reset, {
      type: 'setRangeTime',
      scheduleId: 'sch_kitchen_light',
      rangeId: 'r1',
      field: 'end',
      value: '02:00',
    });
    expect(config.schedules[0]?.ranges[0]?.end).toBe('23:30');
  });

  it('loading a template replaces the schedules and marks the draft dirty', () => {
    const next = draftReducer(initial, {
      type: 'loadTemplate',
      schedules: [
        {
          ...config.schedules[0]!,
          id: 'tpl_schedule',
          ranges: [makeRange({ start: '16:00', end: '20:00' })],
        },
      ],
    });
    expect(next.schedules).toHaveLength(1);
    expect(next.dirty).toBe(true);
  });
});

describe('countActiveRanges', () => {
  it('counts only enabled ranges on enabled schedules', () => {
    expect(countActiveRanges(config.schedules)).toBe(2);

    const disabled = draftReducer(initial, {
      type: 'toggleSchedule',
      scheduleId: 'sch_kitchen_light',
    });
    expect(countActiveRanges(disabled.schedules)).toBe(1);
  });
});

describe('toDraft', () => {
  it('produces the payload the API expects', () => {
    const draft = toDraft(initial, 'tpl_default');
    expect(draft.enabled).toBe(true);
    expect(draft.active_template_id).toBe('tpl_default');
    expect(draft.schedules).toHaveLength(2);
  });
});
