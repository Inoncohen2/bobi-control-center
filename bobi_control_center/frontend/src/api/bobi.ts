/**
 * One typed function per backend endpoint.
 *
 * The only non-GET calls are the probe — which Home Assistant runs with
 * `probe_only=true` — and the managed preview/commit pair, which cannot write
 * unless Home Assistant has declared a write bridge.
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
  AuditLog,
  CommitRequest,
  CommitResponse,
  ManagementStatus,
  PreviewRequest,
  PreviewResponse,
  TaskSnapshot,
  ManagedResource,
  ResourceSnapshot,
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

// --- management ------------------------------------------------------------
const MANAGE = `${ROOT}/manage`;

/**
 * The management contract, discovered from Home Assistant.
 *
 * Carries `writes_enabled` — Home Assistant's master switch. It is read here
 * and nowhere written: there is deliberately no call in this file that could
 * turn it on.
 */
export const fetchManagementContract = () => api.get<ManagementStatus>(`${MANAGE}/contract`);

/** Open and completed tasks, with the bridge's own uid. Read-only. */
export const fetchTaskSnapshot = () => api.get<TaskSnapshot>(`${MANAGE}/tasks/snapshot`);

/** Describe a change. Performs no write — the backend guarantees it. */
export const previewChange = (resource: string, request: PreviewRequest) =>
  api.post<PreviewResponse>(`${MANAGE}/${resource}/preview`, request);

/** Apply a previewed, confirmed change. Refused without a valid preview id. */
export const commitChange = (resource: string, request: CommitRequest) =>
  api.post<CommitResponse>(`${MANAGE}/${resource}/commit`, request);

export const fetchAudit = () => api.get<AuditLog>(`${MANAGE}/audit`);

/**
 * One managed family's current state.
 *
 * Always a 200: a family whose bridge has not landed answers `available:
 * false` with a Hebrew reason, and the screen shows that rather than an error.
 */
export const fetchResourceSnapshot = (resource: ManagedResource) =>
  api.get<ResourceSnapshot>(`${MANAGE}/${encodeURIComponent(resource)}/snapshot`);
