/**
 * One typed function per backend endpoint.
 *
 * Phase 2 is read-only: the only non-GET call is the probe, which Home
 * Assistant guarantees runs with `probe_only=true`.
 *
 * Components never call these directly — they go through `src/hooks/queries.ts`.
 */

import { api } from './client';
import type {
  BridgeCapabilities,
  BridgeDevices,
  BridgeDiagnostics,
  BridgeProbe,
  BridgeRules,
  BridgeShabbat,
  BridgeStatus,
  BridgeTasks,
  BridgeUsers,
  ConnectionInfo,
  DeviceScope,
} from '@/types/api';

const ROOT = '/api/bobi';

export const fetchConnection = () => api.get<ConnectionInfo>(`${ROOT}/connection`);
export const fetchStatus = () => api.get<BridgeStatus>(`${ROOT}/status`);

export const fetchDevices = (scope: DeviceScope = 'all', includeUnavailable = true) =>
  api.get<BridgeDevices>(
    `${ROOT}/devices?scope=${encodeURIComponent(scope)}&include_unavailable=${includeUnavailable}`,
  );

export const fetchCapabilities = () => api.get<BridgeCapabilities>(`${ROOT}/capabilities`);
export const fetchUsers = () => api.get<BridgeUsers>(`${ROOT}/users`);
export const fetchShabbat = () => api.get<BridgeShabbat>(`${ROOT}/shabbat`);
export const fetchRules = () => api.get<BridgeRules>(`${ROOT}/rules`);
export const fetchTasks = () => api.get<BridgeTasks>(`${ROOT}/tasks`);
export const fetchDiagnostics = () => api.get<BridgeDiagnostics>(`${ROOT}/diagnostics`);

/** Probe only — never executes. */
export const runProbe = (text: string) => api.post<BridgeProbe>(`${ROOT}/probe`, { text });
