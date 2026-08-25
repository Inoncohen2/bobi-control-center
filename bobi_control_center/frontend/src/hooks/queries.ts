/**
 * TanStack Query hooks — the only way components read server data.
 *
 * The only mutations are the probe, which is a read of the parser, and the
 * managed preview/commit pair, which lives in `features/manage` because it is
 * a flow rather than a single call.
 */

import { useMutation, useQuery } from '@tanstack/react-query';

import * as bobi from '@/api/bobi';
import type { DeviceScope } from '@/types/api';

export const keys = {
  connection: ['connection'] as const,
  status: ['status'] as const,
  devices: (scope: DeviceScope, includeUnavailable: boolean) =>
    ['devices', scope, includeUnavailable] as const,
  capabilities: ['capabilities'] as const,
  users: ['users'] as const,
  shabbat: ['shabbat'] as const,
  rules: ['rules'] as const,
  tasks: ['tasks'] as const,
  diagnostics: ['diagnostics'] as const,
  managementContract: ['management-contract'] as const,
  taskSnapshot: ['task-snapshot'] as const,
  audit: ['audit'] as const,
};

/**
 * Polling budget.
 *
 * Each poll is a Home Assistant service call, so intervals are deliberately
 * modest. TanStack pauses `refetchInterval` while the document is hidden or the
 * window is unfocused (`refetchIntervalInBackground` defaults to false), so a
 * backgrounded tab costs nothing.
 *
 * Screens whose data rarely changes — capabilities, users, Shabbat, rules,
 * tasks — do not poll at all: they load on entry and serve from cache after.
 */
const LIVE_MS = 20_000; // status, devices
const SLOW_MS = 60_000; // diagnostics

export const useConnection = () =>
  useQuery({ queryKey: keys.connection, queryFn: bobi.fetchConnection });

export const useStatus = () =>
  useQuery({
    queryKey: keys.status,
    queryFn: bobi.fetchStatus,
    refetchInterval: LIVE_MS,
    refetchIntervalInBackground: false,
  });

export const useDevices = (scope: DeviceScope = 'all', includeUnavailable = true) =>
  useQuery({
    queryKey: keys.devices(scope, includeUnavailable),
    queryFn: () => bobi.fetchDevices(scope, includeUnavailable),
    // Scope changes refetch from the bridge; keeping the previous page visible
    // avoids a full-screen spinner on every filter click.
    placeholderData: (previous) => previous,
    refetchInterval: LIVE_MS,
    refetchIntervalInBackground: false,
  });

export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: bobi.fetchCapabilities });

export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: bobi.fetchUsers });
export const useShabbat = () => useQuery({ queryKey: keys.shabbat, queryFn: bobi.fetchShabbat });
export const useRules = () => useQuery({ queryKey: keys.rules, queryFn: bobi.fetchRules });
export const useTasks = () => useQuery({ queryKey: keys.tasks, queryFn: bobi.fetchTasks });

export const useDiagnostics = () =>
  useQuery({
    queryKey: keys.diagnostics,
    queryFn: bobi.fetchDiagnostics,
    refetchInterval: SLOW_MS,
    refetchIntervalInBackground: false,
  });

/** The only POST in Phase 2. Home Assistant runs it with probe_only=true. */
export function useRunProbe() {
  return useMutation({ mutationFn: (text: string) => bobi.runProbe(text) });
}

/**
 * Whether Home Assistant has declared a write bridge.
 *
 * Loaded on entry to a screen that offers management and cached after: this
 * changes only when the Home Assistant side is reconfigured, so polling it
 * would be a service call per interval for nothing.
 */
export const useManagementContract = () =>
  useQuery({ queryKey: keys.managementContract, queryFn: bobi.fetchManagementContract });

/**
 * The task list a change binds to.
 *
 * Only fetched when management is available: without it the read-only screen
 * uses `bobi_cc_tasks`, and one extra service call per visit would buy nothing.
 */
export const useTaskSnapshot = (enabled: boolean) =>
  useQuery({ queryKey: keys.taskSnapshot, queryFn: bobi.fetchTaskSnapshot, enabled });

/** Recent previews and commits. Loaded on entry to the settings screen. */
export const useAudit = () => useQuery({ queryKey: keys.audit, queryFn: bobi.fetchAudit });
