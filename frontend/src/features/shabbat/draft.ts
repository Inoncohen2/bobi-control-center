/**
 * Shabbat draft state.
 *
 * The user edits a *draft*; nothing reaches the server until Preview → Confirm.
 *
 * Note on `crosses_midnight`: it is computed by the backend and arrives on every
 * range. While a range is being edited locally the flag can be momentarily
 * stale, so `localCrossesMidnight` gives the editor an optimistic value. The
 * saved state always uses the server's flag.
 */

import type { ShabbatDeviceSchedule, ShabbatDraft, TimeRange } from '@/types/api';

export type DraftAction =
  | { type: 'reset'; schedules: ShabbatDeviceSchedule[] }
  | { type: 'toggleSchedule'; scheduleId: string }
  | { type: 'toggleRange'; scheduleId: string; rangeId: string }
  | {
      type: 'setRangeTime';
      scheduleId: string;
      rangeId: string;
      field: 'start' | 'end';
      value: string;
    }
  | { type: 'addRange'; scheduleId: string; day: TimeRange['day'] }
  | { type: 'removeRange'; scheduleId: string; rangeId: string }
  | { type: 'loadTemplate'; schedules: ShabbatDeviceSchedule[] };

export interface DraftState {
  schedules: ShabbatDeviceSchedule[];
  /** True once the user has changed anything since the last load or save. */
  dirty: boolean;
}

/** Optimistic local equivalent of the backend's cross-midnight rule. */
export function localCrossesMidnight(start: string, end: string): boolean {
  const toMinutes = (value: string) => {
    const [hours, minutes] = value.split(':');
    return Number(hours) * 60 + Number(minutes);
  };
  return toMinutes(end) <= toMinutes(start);
}

function mapSchedule(
  state: DraftState,
  scheduleId: string,
  update: (schedule: ShabbatDeviceSchedule) => ShabbatDeviceSchedule,
): DraftState {
  return {
    dirty: true,
    schedules: state.schedules.map((schedule) =>
      schedule.id === scheduleId ? update(schedule) : schedule,
    ),
  };
}

function mapRange(
  state: DraftState,
  scheduleId: string,
  rangeId: string,
  update: (range: TimeRange) => TimeRange,
): DraftState {
  return mapSchedule(state, scheduleId, (schedule) => ({
    ...schedule,
    ranges: schedule.ranges.map((range) => (range.id === rangeId ? update(range) : range)),
  }));
}

export function draftReducer(state: DraftState, action: DraftAction): DraftState {
  switch (action.type) {
    case 'reset':
      return { schedules: structuredClone(action.schedules), dirty: false };

    case 'loadTemplate':
      return { schedules: structuredClone(action.schedules), dirty: true };

    case 'toggleSchedule':
      return mapSchedule(state, action.scheduleId, (schedule) => ({
        ...schedule,
        enabled: !schedule.enabled,
      }));

    case 'toggleRange':
      return mapRange(state, action.scheduleId, action.rangeId, (range) => ({
        ...range,
        enabled: !range.enabled,
      }));

    case 'setRangeTime':
      return mapRange(state, action.scheduleId, action.rangeId, (range) => {
        const next = { ...range, [action.field]: action.value } as TimeRange;
        next.crosses_midnight = localCrossesMidnight(next.start, next.end);
        return next;
      });

    case 'addRange':
      return mapSchedule(state, action.scheduleId, (schedule) => ({
        ...schedule,
        ranges: [
          ...schedule.ranges,
          {
            id: `r_${Date.now()}_${schedule.ranges.length}`,
            start: '18:00',
            end: '22:00',
            crosses_midnight: false,
            enabled: true,
            day: action.day,
          },
        ],
      }));

    case 'removeRange':
      return mapSchedule(state, action.scheduleId, (schedule) => ({
        ...schedule,
        ranges: schedule.ranges.filter((range) => range.id !== action.rangeId),
      }));

    default:
      return state;
  }
}

export function toDraft(state: DraftState, activeTemplateId: string | null): ShabbatDraft {
  return { enabled: true, schedules: state.schedules, active_template_id: activeTemplateId };
}

export function countActiveRanges(schedules: ShabbatDeviceSchedule[]): number {
  return schedules
    .filter((schedule) => schedule.enabled)
    .reduce((total, schedule) => total + schedule.ranges.filter((r) => r.enabled).length, 0);
}
