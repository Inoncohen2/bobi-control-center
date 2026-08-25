/** Shared helpers for component tests. */

import type { ReactElement, ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render, type RenderOptions } from '@testing-library/react';
import { vi } from 'vitest';

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // No retries in tests: a failing request should surface immediately.
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = '/', ...options }: RenderOptions & { route?: string } = {},
) {
  const client = createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { client, ...render(ui, { wrapper: Wrapper, ...options }) };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Stub `fetch` with a map of path suffix → JSON payload.
 *
 * Matching ignores the query string so `/devices?scope=climate` still resolves
 * to the `/api/bobi/devices` entry.
 */
export function mockApi(routes: Record<string, unknown>) {
  // `init` is declared even though the router ignores it, so a test can assert
  // which method and body a page actually sent.
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const url = typeof input === 'string' ? input : input.toString();
    const path = url.split('?')[0] as string;
    const match = Object.keys(routes).find((key) => path.endsWith(key));

    if (!match) {
      return json({ code: 'not_found', message: 'לא נמצא', details: {} }, 404);
    }
    return json(routes[match]);
  });
}

/** Stub `fetch` so every request fails the way a disconnected bridge would. */
export function mockDisconnected() {
  return vi.fn(async () =>
    json(
      {
        code: 'upstream_unavailable',
        message: 'לא הצלחתי להתחבר ל-Home Assistant',
        details: { service: 'script.bobi_cc_status' },
      },
      502,
    ),
  );
}
