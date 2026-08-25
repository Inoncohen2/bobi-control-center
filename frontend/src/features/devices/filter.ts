/**
 * Device filtering and grouping.
 *
 * Pure functions, kept out of the component so the rules are testable on their
 * own and the page stays presentational.
 */

import type { Device, DeviceCategory } from '@/types/api';

export type AvailabilityFilter = 'all' | 'available' | 'unavailable';

export interface DeviceFilters {
  search: string;
  room: string | null;
  category: DeviceCategory | null;
  availability: AvailabilityFilter;
}

export const EMPTY_FILTERS: DeviceFilters = {
  search: '',
  room: null,
  category: null,
  availability: 'all',
};

/** Search covers the display name, the room and every alias Bobi understands. */
function matchesSearch(device: Device, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;

  const haystacks = [device.display_name, device.room, ...device.aliases];
  return haystacks.some((value) => value.toLowerCase().includes(needle));
}

export function filterDevices(devices: Device[], filters: DeviceFilters): Device[] {
  return devices.filter((device) => {
    if (!matchesSearch(device, filters.search)) return false;
    if (filters.room && device.room !== filters.room) return false;
    if (filters.category && device.category !== filters.category) return false;
    if (filters.availability === 'available' && !device.available) return false;
    if (filters.availability === 'unavailable' && device.available) return false;
    return true;
  });
}

/** Group by room, preserving the room order the API supplied. */
export function groupByRoom(devices: Device[], roomOrder: string[]): Array<[string, Device[]]> {
  const groups = new Map<string, Device[]>();
  for (const device of devices) {
    const existing = groups.get(device.room);
    if (existing) existing.push(device);
    else groups.set(device.room, [device]);
  }

  const ordered: Array<[string, Device[]]> = [];
  for (const room of roomOrder) {
    const found = groups.get(room);
    if (found) {
      ordered.push([room, found]);
      groups.delete(room);
    }
  }
  // Any room not in the supplied order still gets rendered.
  return [...ordered, ...groups.entries()];
}

export function hasActiveFilters(filters: DeviceFilters): boolean {
  return (
    filters.search.trim() !== '' ||
    filters.room !== null ||
    filters.category !== null ||
    filters.availability !== 'all'
  );
}
