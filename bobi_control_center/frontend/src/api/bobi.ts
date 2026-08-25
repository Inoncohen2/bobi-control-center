/**
 * One typed function per Bobi Management API endpoint.
 *
 * Components never call `api.*` directly — they go through the hooks in
 * `src/hooks`, which call these.
 */

import { api } from './client';
import type {
  AuditLog,
  Automation,
  AutomationDraft,
  AutomationList,
  CalendarList,
  Capability,
  ChangePreview,
  Device,
  DeviceList,
  DiagnosticsReport,
  NotificationList,
  NotificationRule,
  OperationResult,
  Permission,
  ProbeHistory,
  ProbeResult,
  SettingsResponse,
  ShabbatConfig,
  ShabbatDeviceSchedule,
  ShabbatDraft,
  ShabbatTemplate,
  SystemStatus,
  Task,
  TaskList,
  TestReport,
  User,
  UserList,
} from '@/types/api';

const ROOT = '/api/bobi';

// --- status ----------------------------------------------------------------
export const fetchStatus = () => api.get<SystemStatus>(`${ROOT}/status`);

// --- capabilities ----------------------------------------------------------
export const fetchCapabilities = () => api.get<Capability[]>(`${ROOT}/capabilities`);
export const fetchCapability = (id: string) => api.get<Capability>(`${ROOT}/capabilities/${id}`);
export const toggleCapability = (id: string, enabled: boolean) =>
  api.post<Capability>(`${ROOT}/capabilities/${id}/toggle`, { enabled });

// --- devices ---------------------------------------------------------------
export const fetchDevices = () => api.get<DeviceList>(`${ROOT}/devices`);
export const fetchDevice = (id: string) => api.get<Device>(`${ROOT}/devices/${id}`);

// --- automations -----------------------------------------------------------
export const fetchAutomations = () => api.get<AutomationList>(`${ROOT}/automations`);
export const fetchAutomation = (id: string) => api.get<Automation>(`${ROOT}/automations/${id}`);
export const previewAutomation = (draft: AutomationDraft) =>
  api.post<ChangePreview>(`${ROOT}/automations/preview`, draft);
export const confirmAutomation = (draft: AutomationDraft, token: string) =>
  api.post<OperationResult>(`${ROOT}/automations/confirm`, { draft, token });
export const previewDeleteAutomation = (id: string) =>
  api.post<ChangePreview>(`${ROOT}/automations/${id}/delete/preview`);
export const confirmDeleteAutomation = (id: string, token: string) =>
  api.post<OperationResult>(`${ROOT}/automations/${id}/delete/confirm`, { token });
export const toggleAutomation = (id: string, enabled: boolean) =>
  api.post<Automation>(`${ROOT}/automations/${id}/toggle`, { enabled });
export const duplicateAutomation = (id: string) =>
  api.post<Automation>(`${ROOT}/automations/${id}/duplicate`);

// --- shabbat ---------------------------------------------------------------
export const fetchShabbat = () => api.get<ShabbatConfig>(`${ROOT}/shabbat`);
export const previewShabbat = (draft: ShabbatDraft) =>
  api.post<ChangePreview>(`${ROOT}/shabbat/preview`, draft);
export const confirmShabbat = (draft: ShabbatDraft, token: string) =>
  api.post<OperationResult>(`${ROOT}/shabbat/confirm`, { draft, token });
export const saveShabbatTemplate = (
  name: string,
  description: string,
  schedules: ShabbatDeviceSchedule[],
) => api.post<ShabbatTemplate>(`${ROOT}/shabbat/templates`, { name, description, schedules });

// --- notifications ---------------------------------------------------------
export const fetchNotifications = () => api.get<NotificationList>(`${ROOT}/notifications`);
export const toggleNotification = (id: string, enabled: boolean) =>
  api.post<NotificationRule>(`${ROOT}/notifications/${id}/toggle`, { enabled });

// --- users -----------------------------------------------------------------
export const fetchUsers = () => api.get<UserList>(`${ROOT}/users`);
export const fetchUser = (id: string) => api.get<User>(`${ROOT}/users/${id}`);
export const previewPermissions = (userId: string, permissions: Permission[]) =>
  api.post<ChangePreview>(`${ROOT}/users/${userId}/permissions/preview`, { permissions });
export const confirmPermissions = (userId: string, permissions: Permission[], token: string) =>
  api.post<OperationResult>(`${ROOT}/users/${userId}/permissions/confirm`, {
    payload: { permissions },
    token,
  });

// --- tasks & calendar ------------------------------------------------------
export const fetchTasks = () => api.get<TaskList>(`${ROOT}/tasks`);
export const updateTask = (id: string, patch: { completed?: boolean; title?: string }) =>
  api.patch<Task>(`${ROOT}/tasks/${id}`, patch);
export const deleteTask = (id: string) => api.delete<OperationResult>(`${ROOT}/tasks/${id}`);
export const fetchCalendar = () => api.get<CalendarList>(`${ROOT}/calendar`);

// --- probe -----------------------------------------------------------------
export const runProbe = (text: string) => api.post<ProbeResult>(`${ROOT}/probe`, { text });
export const fetchProbeHistory = () => api.get<ProbeHistory>(`${ROOT}/probe/history`);

// --- diagnostics, tests, audit, settings -----------------------------------
export const fetchDiagnostics = () => api.get<DiagnosticsReport>(`${ROOT}/diagnostics`);
export const fetchTests = () => api.get<TestReport>(`${ROOT}/tests`);
export const runTests = () => api.post<TestReport>(`${ROOT}/tests/run`);
export const fetchAudit = () => api.get<AuditLog>(`${ROOT}/audit`);
export const fetchSettings = () => api.get<SettingsResponse>(`${ROOT}/settings`);
