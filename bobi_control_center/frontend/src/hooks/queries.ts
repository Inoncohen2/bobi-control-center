/**
 * TanStack Query hooks — the only way components read server data.
 *
 * Phase 2 has no mutations except the probe, which is a read of the parser.
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
};

export const useConnection = () =>
  useQuery({ queryKey: keys.connection, queryFn: bobi.fetchConnection });

export const useStatus = () => useQuery({ queryKey: keys.status, queryFn: bobi.fetchStatus });

export const useDevices = (scope: DeviceScope = 'all', includeUnavailable = true) =>
  useQuery({
    queryKey: keys.devices(scope, includeUnavailable),
    queryFn: () => bobi.fetchDevices(scope, includeUnavailable),
    // Scope changes refetch from the bridge; keeping the previous page visible
    // avoids a full-screen spinner on every filter click.
    placeholderData: (previous) => previous,
  });

export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: bobi.fetchCapabilities });

export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: bobi.fetchUsers });
export const useShabbat = () => useQuery({ queryKey: keys.shabbat, queryFn: bobi.fetchShabbat });
export const useRules = () => useQuery({ queryKey: keys.rules, queryFn: bobi.fetchRules });
export const useTasks = () => useQuery({ queryKey: keys.tasks, queryFn: bobi.fetchTasks });

export const useDiagnostics = () =>
  useQuery({ queryKey: keys.diagnostics, queryFn: bobi.fetchDiagnostics });

/** The only POST in Phase 2. Home Assistant runs it with probe_only=true. */
export function useRunProbe() {
  return useMutation({ mutationFn: (text: string) => bobi.runProbe(text) });
}
