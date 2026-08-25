import { describe, expect, it } from 'vitest';

import { makeDevice } from '@/test/fixtures';
import {
  EMPTY_FILTERS,
  filterDevices,
  groupByRoom,
  hasActiveFilters,
} from './filter';

const devices = [
  makeDevice({ id: 'kitchen_light', display_name: 'אור מטבח', room: 'מטבח', category: 'light' }),
  makeDevice({
    id: 'living_room_ac',
    display_name: 'מזגן סלון',
    room: 'סלון',
    category: 'climate',
    aliases: ['מזגן סלון', 'המזגן בסלון'],
  }),
  makeDevice({
    id: 'lia_camera',
    display_name: 'מצלמת ליה',
    room: 'חדר בנות',
    category: 'camera',
    available: false,
    state: 'unavailable',
    state_label: 'לא זמין',
  }),
];

describe('filterDevices', () => {
  it('returns everything when no filter is set', () => {
    expect(filterDevices(devices, EMPTY_FILTERS)).toHaveLength(3);
  });

  it('matches on the display name', () => {
    const result = filterDevices(devices, { ...EMPTY_FILTERS, search: 'מזגן' });
    expect(result.map((device) => device.id)).toEqual(['living_room_ac']);
  });

  it('matches on an alias the user might speak', () => {
    const result = filterDevices(devices, { ...EMPTY_FILTERS, search: 'המזגן בסלון' });
    expect(result.map((device) => device.id)).toEqual(['living_room_ac']);
  });

  it('matches on the room name', () => {
    const result = filterDevices(devices, { ...EMPTY_FILTERS, search: 'חדר בנות' });
    expect(result.map((device) => device.id)).toEqual(['lia_camera']);
  });

  it('ignores surrounding whitespace', () => {
    expect(filterDevices(devices, { ...EMPTY_FILTERS, search: '   ' })).toHaveLength(3);
  });

  it('filters by room', () => {
    const result = filterDevices(devices, { ...EMPTY_FILTERS, room: 'מטבח' });
    expect(result.map((device) => device.id)).toEqual(['kitchen_light']);
  });

  it('filters by category', () => {
    const result = filterDevices(devices, { ...EMPTY_FILTERS, category: 'camera' });
    expect(result.map((device) => device.id)).toEqual(['lia_camera']);
  });

  it('filters by availability', () => {
    expect(
      filterDevices(devices, { ...EMPTY_FILTERS, availability: 'unavailable' }).map((d) => d.id),
    ).toEqual(['lia_camera']);
    expect(
      filterDevices(devices, { ...EMPTY_FILTERS, availability: 'available' }),
    ).toHaveLength(2);
  });

  it('combines filters', () => {
    const result = filterDevices(devices, {
      search: 'מזגן',
      room: 'סלון',
      category: 'climate',
      availability: 'available',
    });
    expect(result).toHaveLength(1);
  });

  it('returns nothing when filters conflict', () => {
    const result = filterDevices(devices, { ...EMPTY_FILTERS, room: 'מטבח', category: 'camera' });
    expect(result).toEqual([]);
  });
});

describe('groupByRoom', () => {
  it('respects the room order supplied by the API', () => {
    const grouped = groupByRoom(devices, ['סלון', 'מטבח', 'חדר בנות']);
    expect(grouped.map(([room]) => room)).toEqual(['סלון', 'מטבח', 'חדר בנות']);
  });

  it('still renders rooms missing from the supplied order', () => {
    const grouped = groupByRoom(devices, ['סלון']);
    expect(grouped.map(([room]) => room)).toEqual(['סלון', 'מטבח', 'חדר בנות']);
  });
});

describe('hasActiveFilters', () => {
  it('is false for the empty filter set', () => {
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false);
  });

  it('ignores a whitespace-only search', () => {
    expect(hasActiveFilters({ ...EMPTY_FILTERS, search: '  ' })).toBe(false);
  });

  it('is true once anything is set', () => {
    expect(hasActiveFilters({ ...EMPTY_FILTERS, room: 'מטבח' })).toBe(true);
    expect(hasActiveFilters({ ...EMPTY_FILTERS, availability: 'unavailable' })).toBe(true);
  });
});
