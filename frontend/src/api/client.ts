/**
 * The only place in the frontend that talks HTTP.
 *
 * Every failure becomes an `ApiError` carrying a Hebrew message safe to show a
 * user, plus technical detail that the UI reveals only under "פרטים טכניים".
 */

import type { ApiErrorBody } from '@/types/api';

/** Same-origin in every mode: Vite proxies `/api` in dev, FastAPI serves it in production. */
const BASE_URL = '';

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
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch (cause) {
    throw new ApiError(NETWORK_ERROR_MESSAGE, 'network_error', 0, {
      reason: cause instanceof Error ? cause.message : String(cause),
    });
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

/** Turn any thrown value into something safe to display. */
export function toDisplayError(error: unknown, fallback: string): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError(fallback, 'unknown_error', 0, {
    reason: error instanceof Error ? error.message : String(error),
  });
}
