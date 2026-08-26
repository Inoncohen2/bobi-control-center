/**
 * What this session is allowed to do, as the server decided it.
 *
 * The role is read from `/api/auth/session` and never chosen here. This is a
 * copy of the backend's ordering used for one purpose only: not drawing a
 * control the server would refuse. The refusal itself lives in the backend and
 * runs whatever this file says — if the two ever disagree, the screen shows a
 * button that returns 403, which is a cosmetic bug rather than a hole.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';

export type Role = 'viewer' | 'operator' | 'admin' | 'owner';

/** Weakest first. Position in this array is the privilege ordering. */
const ORDER: Role[] = ['viewer', 'operator', 'admin', 'owner'];

/** The least privileged role allowed to run an operation of each risk. */
const MINIMUM: Record<string, Role> = {
  read_only: 'viewer',
  low: 'operator',
  medium: 'operator',
  high: 'admin',
  destructive: 'owner',
};

interface SessionStatus {
  authenticated: boolean;
  mode: 'home_assistant' | 'external';
  role?: Role;
  role_label?: string;
}

function rank(role: Role | undefined): number {
  const index = role ? ORDER.indexOf(role) : -1;
  // An unknown role is the weakest one, matching the backend: the failure mode
  // of not recognising a role is "can only read", never "can do anything".
  return index < 0 ? 0 : index;
}

/** A risk the UI does not recognise is treated as admin-level, as the backend does. */
export function allows(role: Role | undefined, risk: string | undefined): boolean {
  return rank(role) >= rank(MINIMUM[risk ?? ''] ?? 'admin');
}

export const sessionKey = ['auth-session'] as const;

/**
 * The current session's role.
 *
 * Cached for the life of the tab: a role changes when someone logs in again,
 * which remounts everything anyway. Undefined while loading, and undefined
 * reads as `viewer` in {@link allows} — so controls appear once the answer is
 * in rather than flickering into existence before it.
 */
export function useRole(): { role: Role | undefined; label: string | undefined } {
  const query = useQuery({
    queryKey: sessionKey,
    queryFn: () => api.get<SessionStatus>('/api/auth/session'),
    staleTime: Infinity,
    retry: false,
  });
  return { role: query.data?.role, label: query.data?.role_label };
}
