/**
 * The contract-driven screens, from a household member's point of view.
 *
 * These defend the property that makes the whole design safe: **a control
 * appears only because the bridge said it could**. Every other guarantee in the
 * release rests on that one, and it is the guarantee most easily lost to a
 * refactor, because losing it looks like the page working better.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SettingsManagePage } from '@/pages/SettingsManagePage';
import { SystemPage } from '@/pages/SystemPage';
import { CamerasPage } from '@/pages/CamerasPage';
import {
  makeConnection,
  makeManagedItem,
  makeManagementOff,
  makeManagementOn,
  makeManagementWith,
  makePreview,
  makeResourceSnapshot,
  makeStatus,
} from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';

const BASE = {
  '/api/bobi/connection': makeConnection(),
  '/api/bobi/status': makeStatus(),
};

function routes(overrides: Record<string, unknown> = {}) {
  return {
    ...BASE,
    '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: true }),
    '/api/bobi/manage/settings/snapshot': makeResourceSnapshot(),
    '/api/bobi/manage/settings/preview': makePreview(),
    ...overrides,
  };
}

/** Install a stubbed fetch, and hand the mock back so a test can inspect it. */
function stub(routes: Record<string, unknown>) {
  const fetchMock = mockApi(routes);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Every path the page fetched. */
function paths(fetchMock: ReturnType<typeof mockApi>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input));
}

describe('a family the bridge has not declared', () => {
  it('says so, asks for nothing, and offers no controls', async () => {
    const fetchMock = stub({
      ...BASE,
      '/api/bobi/manage/contract': makeManagementOn(),
    });
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText(/עדיין לא זמין לניהול/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /כבה|הפעל/ })).not.toBeInTheDocument();
    // And it did not ask for a snapshot it already knew was not there.
    await waitFor(() => expect(paths(fetchMock).length).toBeGreaterThan(0));
    expect(paths(fetchMock).some((path) => path.includes('/settings/snapshot'))).toBe(false);
  });

  it('says management is off entirely when there is no bridge at all', async () => {
    stub({ ...BASE, '/api/bobi/manage/contract': makeManagementOff() });
    renderWithProviders(<SettingsManagePage />);

    // The heading and the reason the bridge gave say the same sentence.
    expect(await screen.findAllByText(/ניהול עדיין לא הופעל ב-Home Assistant/)).not.toHaveLength(
      0,
    );
  });
});

describe('an item the bridge did not mark controllable', () => {
  it('renders as a reading, with no control', async () => {
    stub(
      routes({
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [makeManagedItem({ controllable: false, display: 'פעיל' })],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText('סיכום בוקר אוטומטי')).toBeInTheDocument();
    expect(screen.getByText('פעיל')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'כבה' })).not.toBeInTheDocument();
  });

  it('renders as a reading when the bridge named no operations', async () => {
    stub(
      routes({
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [makeManagedItem({ controllable: true, operations: [] })],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    await screen.findByText('סיכום בוקר אוטומטי');
    expect(screen.queryByRole('button', { name: 'כבה' })).not.toBeInTheDocument();
  });

  it('shows the reason the bridge gave for it being unavailable', async () => {
    stub(
      routes({
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              controllable: false,
              unavailable_reason: 'הרכיב הזה לא מחובר כרגע',
            }),
          ],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText('הרכיב הזה לא מחובר כרגע')).toBeInTheDocument();
  });
});

describe('with the master write switch off', () => {
  it('shows the values, explains, and offers no control', async () => {
    stub(
      routes({
        '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: false }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText(/שינויים כבויים כרגע/)).toBeInTheDocument();
    // Not presented as a fault — nothing is broken.
    expect(screen.queryByText(/שגיאה|נכשל/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'כבה' })).not.toBeInTheDocument();
  });
});

describe('a control the bridge did advertise', () => {
  it('asks for a preview and writes nothing by itself', async () => {
    const fetchMock = stub(routes());
    renderWithProviders(<SettingsManagePage />);

    await userEvent.click(await screen.findByRole('button', { name: 'כבה' }));

    await waitFor(() =>
      expect(paths(fetchMock).some((path) => path.endsWith('/settings/preview'))).toBe(true),
    );
    // A preview, and not a commit. Pressing a control never writes.
    expect(paths(fetchMock).some((path) => path.endsWith('/settings/commit'))).toBe(false);
  });

  it('bounds a number by the limits the bridge published', async () => {
    stub(
      routes({
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              id: 'ai_monthly_cap',
              label: 'תקרת עלות חודשית',
              kind: 'number',
              value: 20,
              constraints: {
                minimum: 0,
                maximum: 200,
                step: 5,
                unit: '$',
                max_length: null,
                allowed: [],
              },
            }),
          ],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    const field = await screen.findByLabelText('תקרת עלות חודשית');
    expect(field).toHaveAttribute('min', '0');
    expect(field).toHaveAttribute('max', '200');
    expect(field).toHaveAttribute('step', '5');
  });

  it('offers only the options the bridge published', async () => {
    stub(
      routes({
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              id: 'home_status_policy',
              label: 'מתי לשלוח',
              kind: 'choice',
              value: 'away_only',
              options: [
                { value: 'away_only', label: 'רק כשאין אף אחד בבית', detail: null },
                { value: 'always', label: 'תמיד', detail: null },
              ],
            }),
          ],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    const select = await screen.findByLabelText('מתי לשלוח');
    const values = Array.from(select.querySelectorAll('option')).map((option) => option.value);
    expect(values).toEqual(['away_only', 'always']);
  });
});

describe('the system screen', () => {
  it('says plainly that restarts and restores are not done from here', async () => {
    stub({
      ...BASE,
      '/api/bobi/manage/contract': makeManagementWith('system', { writes_enabled: true }),
      '/api/bobi/manage/system/snapshot': makeResourceSnapshot({ resource: 'system' }),
    });
    renderWithProviders(<SystemPage />);

    expect(await screen.findByText(/אינן\s*מתבצעות מכאן|אינן מתבצעות מכאן/)).toBeInTheDocument();
  });
});

describe('the cameras screen', () => {
  it('promises not to switch a camera on to look at it', async () => {
    stub({
      ...BASE,
      '/api/bobi/manage/contract': makeManagementWith('devices', { writes_enabled: true }),
      '/api/bobi/manage/devices/snapshot': makeResourceSnapshot({
        resource: 'devices',
        items: [
          makeManagedItem({
            id: 'cam_lia',
            label: 'מצלמת ליה',
            kind: 'readonly',
            value: 'streaming',
            display: 'משדרת',
            controllable: false,
            operations: [],
            detail: { device_class: 'camera' },
          }),
        ],
      }),
    });
    renderWithProviders(<CamerasPage />);

    // Wait on the row, not on the intro: the intro is static text and would
    // resolve before the snapshot had loaded.
    expect(await screen.findByText('מצלמת ליה')).toBeInTheDocument();
    expect(screen.getByText(/מצלמה כבויה נשארת כבויה/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /הפעל|כבה/ })).not.toBeInTheDocument();
  });
});
