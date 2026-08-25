/**
 * Client-side device filtering and grouping.
 *
 * Scope is applied by the bridge (a server round trip), because the bridge owns
 * the semantic-scope definitions. Search, area and availability are applied
 * here over whatever the bridge returned.
 */

import type { BridgeDevice } from '@/types/api';
import { deviceName, isAvailable } from '@/utils/format';

export type AvailabilityFilter = 'all' | 'available' | 'unavailable';

export interface DeviceFilters {
  search: string;
  area: string | null;
  availability: AvailabilityFilter;
}

export const EMPTY_FILTERS: DeviceFilters = {
  search: '',
  area: null,
  availability: 'all',
};

/** Search covers the display name, the area and every alias Bobi understands. */
function matchesSearch(device: BridgeDevice, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;

  const haystacks = [
    deviceName(device),
    device.area ?? '',
    device.group ?? '',
    ...(device.aliases ?? []),
  ];
  return haystacks.some((value) => value.toLowerCase().includes(needle));
}

export function filterDevices(devices: BridgeDevice[], filters: DeviceFilters): BridgeDevice[] {
  return devices.filter((device) => {
    if (!matchesSearch(device, filters.search)) return false;
    if (filters.area && device.area !== filters.area) return false;

    const available = isAvailable(device.state);
    if (filters.availability === 'available' && !available) return false;
    if (filters.availability === 'unavailable' && available) return false;
    return true;
  });
}

/** Group by area, with unassigned devices last. */
export function groupByArea(devices: BridgeDevice[]): Array<[string, BridgeDevice[]]> {
  const groups = new Map<string, BridgeDevice[]>();
  for (const device of devices) {
    const area = device.area ?? 'ללא חדר';
    const existing = groups.get(area);
    if (existing) existing.push(device);
    else groups.set(area, [device]);
  }

  return [...groups.entries()].sort(([a], [b]) => {
    if (a === 'ללא חדר') return 1;
    if (b === 'ללא חדר') return -1;
    return a.localeCompare(b, 'he');
  });
}

export function areasOf(devices: BridgeDevice[]): string[] {
  return [...new Set(devices.map((d) => d.area).filter((a): a is string => Boolean(a)))].sort(
    (a, b) => a.localeCompare(b, 'he'),
  );
}

export function hasActiveFilters(filters: DeviceFilters): boolean {
  return (
    filters.search.trim() !== '' || filters.area !== null || filters.availability !== 'all'
  );
}
