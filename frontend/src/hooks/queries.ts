/**
 * TanStack Query hooks — the only way components read or write server data.
 *
 * Query keys are centralised in `keys` so an invalidation after a mutation
 * cannot silently miss a cache entry.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as bobi from '@/api/bobi';
import type { AutomationDraft, Permission, ShabbatDraft } from '@/types/api';

export const keys = {
  status: ['status'] as const,
  capabilities: ['capabilities'] as const,
  capability: (id: string) => ['capabilities', id] as const,
  devices: ['devices'] as const,
  device: (id: string) => ['devices', id] as const,
  automations: ['automations'] as const,
  automation: (id: string) => ['automations', id] as const,
  shabbat: ['shabbat'] as const,
  notifications: ['notifications'] as const,
  users: ['users'] as const,
  tasks: ['tasks'] as const,
  calendar: ['calendar'] as const,
  probeHistory: ['probe', 'history'] as const,
  diagnostics: ['diagnostics'] as const,
  tests: ['tests'] as const,
  audit: ['audit'] as const,
  settings: ['settings'] as const,
};

// --- reads -----------------------------------------------------------------
export const useStatus = () => useQuery({ queryKey: keys.status, queryFn: bobi.fetchStatus });

export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: bobi.fetchCapabilities });

export const useCapability = (id: string) =>
  useQuery({ queryKey: keys.capability(id), queryFn: () => bobi.fetchCapability(id) });

export const useDevices = () => useQuery({ queryKey: keys.devices, queryFn: bobi.fetchDevices });

export const useAutomations = () =>
  useQuery({ queryKey: keys.automations, queryFn: bobi.fetchAutomations });

export const useAutomation = (id: string | undefined) =>
  useQuery({
    queryKey: keys.automation(id ?? ''),
    queryFn: () => bobi.fetchAutomation(id as string),
    enabled: Boolean(id),
  });

export const useShabbat = () => useQuery({ queryKey: keys.shabbat, queryFn: bobi.fetchShabbat });

export const useNotifications = () =>
  useQuery({ queryKey: keys.notifications, queryFn: bobi.fetchNotifications });

export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: bobi.fetchUsers });

export const useTasks = () => useQuery({ queryKey: keys.tasks, queryFn: bobi.fetchTasks });

export const useCalendar = () => useQuery({ queryKey: keys.calendar, queryFn: bobi.fetchCalendar });

export const useProbeHistory = () =>
  useQuery({ queryKey: keys.probeHistory, queryFn: bobi.fetchProbeHistory });

export const useDiagnostics = () =>
  useQuery({ queryKey: keys.diagnostics, queryFn: bobi.fetchDiagnostics });

export const useTests = () => useQuery({ queryKey: keys.tests, queryFn: bobi.fetchTests });

export const useAudit = () => useQuery({ queryKey: keys.audit, queryFn: bobi.fetchAudit });

export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: bobi.fetchSettings });

// --- writes ----------------------------------------------------------------
/** Anything that writes also refreshes the dashboard and the audit log. */
function useInvalidate() {
  const client = useQueryClient();
  return (...extra: ReadonlyArray<readonly unknown[]>) => {
    void client.invalidateQueries({ queryKey: keys.status });
    void client.invalidateQueries({ queryKey: keys.audit });
    extra.forEach((key) => void client.invalidateQueries({ queryKey: key }));
  };
}

export function useToggleCapability() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      bobi.toggleCapability(id, enabled),
    onSuccess: (_data, variables) =>
      invalidate(keys.capabilities, keys.capability(variables.id)),
  });
}

export function useToggleAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      bobi.toggleAutomation(id, enabled),
    onSuccess: () => invalidate(keys.automations),
  });
}

export function useDuplicateAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => bobi.duplicateAutomation(id),
    onSuccess: () => invalidate(keys.automations),
  });
}

export function usePreviewAutomation() {
  return useMutation({ mutationFn: (draft: AutomationDraft) => bobi.previewAutomation(draft) });
}

export function useConfirmAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ draft, token }: { draft: AutomationDraft; token: string }) =>
      bobi.confirmAutomation(draft, token),
    onSuccess: () => invalidate(keys.automations),
  });
}

export function usePreviewDeleteAutomation() {
  return useMutation({ mutationFn: (id: string) => bobi.previewDeleteAutomation(id) });
}

export function useConfirmDeleteAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, token }: { id: string; token: string }) =>
      bobi.confirmDeleteAutomation(id, token),
    onSuccess: () => invalidate(keys.automations),
  });
}

export function usePreviewShabbat() {
  return useMutation({ mutationFn: (draft: ShabbatDraft) => bobi.previewShabbat(draft) });
}

export function useConfirmShabbat() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ draft, token }: { draft: ShabbatDraft; token: string }) =>
      bobi.confirmShabbat(draft, token),
    onSuccess: () => invalidate(keys.shabbat),
  });
}

export function useSaveShabbatTemplate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: Parameters<typeof bobi.saveShabbatTemplate>) =>
      bobi.saveShabbatTemplate(...input),
    onSuccess: () => invalidate(keys.shabbat),
  });
}

export function useToggleNotification() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      bobi.toggleNotification(id, enabled),
    onSuccess: () => invalidate(keys.notifications),
  });
}

export function usePreviewPermissions() {
  return useMutation({
    mutationFn: ({ userId, permissions }: { userId: string; permissions: Permission[] }) =>
      bobi.previewPermissions(userId, permissions),
  });
}

export function useConfirmPermissions() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({
      userId,
      permissions,
      token,
    }: {
      userId: string;
      permissions: Permission[];
      token: string;
    }) => bobi.confirmPermissions(userId, permissions, token),
    onSuccess: () => invalidate(keys.users),
  });
}

export function useUpdateTask() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { completed?: boolean; title?: string } }) =>
      bobi.updateTask(id, patch),
    onSuccess: () => invalidate(keys.tasks),
  });
}

export function useDeleteTask() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => bobi.deleteTask(id),
    onSuccess: () => invalidate(keys.tasks),
  });
}

export function useRunProbe() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (text: string) => bobi.runProbe(text),
    onSuccess: () => invalidate(keys.probeHistory),
  });
}

export function useRunTests() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: bobi.runTests, onSuccess: () => invalidate(keys.tests) });
}
