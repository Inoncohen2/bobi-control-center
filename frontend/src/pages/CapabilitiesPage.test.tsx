import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CapabilitiesPage } from './CapabilitiesPage';
import { advanced } from '@/test/fixtures';
import { renderWithProviders } from '@/test/utils';
import type { Capability } from '@/types/api';

function makeCapability(overrides: Partial<Capability> = {}): Capability {
  return {
    id: 'vision',
    name: 'עיבוד תמונות',
    description: 'זיהוי מה רואים בתמונה.',
    icon: 'image',
    group: 'בינה מלאכותית',
    enabled: false,
    state: 'offline',
    state_label: 'כבוי',
    warning: null,
    settings: [],
    related_device_ids: [],
    last_used: null,
    advanced,
    ...overrides,
  };
}

const capabilities = [
  makeCapability(),
  makeCapability({
    id: 'cameras',
    name: 'מצלמות',
    description: 'צילום תמונה מהמצלמות.',
    group: 'שליטה בבית',
    enabled: true,
    state: 'degraded',
    state_label: 'פעיל חלקית',
    warning: 'שתי מצלמות אינן זמינות כרגע.',
    settings: [
      { key: 'recipient', label: 'נמען', type: 'select', value: 'ינון', options: [], help: null },
    ],
  }),
];

describe('CapabilitiesPage', () => {
  it('groups capabilities and surfaces warnings', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify(capabilities), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    );
    renderWithProviders(<CapabilitiesPage />);

    expect(await screen.findByText('עיבוד תמונות')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'בינה מלאכותית' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'שליטה בבית' })).toBeInTheDocument();
    expect(screen.getByText('שתי מצלמות אינן זמינות כרגע.')).toBeInTheDocument();
  });

  it('sends a toggle and reflects the result', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();
      if (init?.method === 'POST' && url.includes('/toggle')) {
        return new Response(
          JSON.stringify(makeCapability({ enabled: true, state_label: 'פעיל' })),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify(capabilities), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<CapabilitiesPage />);
    await screen.findByText('עיבוד תמונות');

    const toggle = screen.getByRole('switch', { name: /עיבוד תמונות/ });
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    await user.click(toggle);

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
      expect(posted?.[0]?.toString()).toContain('/api/bobi/capabilities/vision/toggle');
      expect(posted?.[1]?.body).toBe(JSON.stringify({ enabled: true }));
    });
  });

  it('opens a detail drawer with the capability settings', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify(capabilities), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    );
    renderWithProviders(<CapabilitiesPage />);
    await screen.findByText('מצלמות');

    await user.click(screen.getByRole('button', { name: 'הגדרות של מצלמות' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('מצלמות');
    expect(dialog).toHaveTextContent('נמען');
    expect(dialog).toHaveTextContent('ינון');
  });

  it('reports a failed toggle in Hebrew', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return new Response(
            JSON.stringify({
              code: 'not_found',
              message: 'לא מצאתי את היכולת הזו',
              details: {},
            }),
            { status: 404, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response(JSON.stringify(capabilities), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );

    renderWithProviders(<CapabilitiesPage />);
    await screen.findByText('עיבוד תמונות');

    await user.click(screen.getByRole('switch', { name: /עיבוד תמונות/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('לא מצאתי את היכולת הזו');
  });
});
