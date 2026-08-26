/**
 * The only place in the frontend that talks HTTP.
 *
 * ## Ingress-safe URLs
 *
 * Home Assistant serves this app from a generated prefix such as
 * `/api/hassio_ingress/<token>/`, which changes between sessions and must never
 * be hard-coded. Requests are therefore built **relative to the document's own
 * base path**, derived at runtime from `location.pathname`:
 *
 *   served at `/api/hassio_ingress/abc123/`  → base `/api/hassio_ingress/abc123`
 *   served at `/`                            → base `''`
 *
 * Combined with a HashRouter (so the router never touches the path) and Vite's
 * `base: './'` (so assets resolve relatively), the same bundle works at the
 * domain root in development and under any Ingress prefix in production.
 */

import type { ApiErrorBody } from '@/types/api';

/**
 * Derive the app root from the current URL.
 *
 * The hash is ignored entirely — with a HashRouter the path is always the app
 * root, so whatever precedes the hash is the prefix Ingress gave us. A trailing
 * `index.html` is stripped so a direct file URL still resolves correctly.
 */
export function resolveBasePath(pathname: string): string {
  let path = pathname;

  const fileIndex = path.lastIndexOf('/');
  const lastSegment = fileIndex >= 0 ? path.slice(fileIndex + 1) : '';
  if (lastSegment.includes('.')) {
    // e.g. ".../index.html" → drop the file, keep the directory.
    path = path.slice(0, fileIndex);
  }

  // Normalise: no trailing slash, and "/" becomes "" so we never emit "//api".
  path = path.replace(/\/+$/, '');
  return path;
}

function currentBase(): string {
  if (typeof window === 'undefined') return '';
  return resolveBasePath(window.location.pathname);
}

/** Build an absolute-on-this-origin URL for an API path. */
export function apiUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${currentBase()}${suffix}`;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(message: string, code: string, status: number, details: Record<string, unknown>) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** True when the backend could not reach Home Assistant. */
  get isDisconnected(): boolean {
    return (
      this.code === 'network_error' ||
      this.code === 'upstream_unavailable' ||
      this.code === 'ha_unauthorized' ||
      this.code === 'bridge_service_missing' ||
      this.status === 502
    );
  }

  /** What to render under the "פרטים טכניים" disclosure. */
  get technical(): string {
    const parts = [`code: ${this.code}`, `status: ${this.status}`];
    if (Object.keys(this.details).length > 0) {
      parts.push(`details: ${JSON.stringify(this.details, null, 2)}`);
    }
    return parts.join('\n');
  }
}

const NETWORK_ERROR_MESSAGE = 'אין חיבור לשרת של בובי';

async function parseError(response: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> = {};
  try {
    body = (await response.json()) as Partial<ApiErrorBody>;
  } catch {
    // A non-JSON error body is itself technical detail we should not show.
  }
  return new ApiError(
    body.message ?? 'משהו השתבש',
    body.code ?? `http_${response.status}`,
    response.status,
    body.details ?? {},
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    throw new ApiError(NETWORK_ERROR_MESSAGE, 'network_error', 0, {
      reason: cause instanceof Error ? cause.message : String(cause),
    });
  }

  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
};

/** Turn any thrown value into something safe to display. */
export function toDisplayError(error: unknown, fallback: string): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(fallback, 'unknown_error', 0, {
    reason: error instanceof Error ? error.message : String(error),
  });
}
