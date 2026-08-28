/**
 * The Shabbat profile editor, against the shape the live bridge really sends.
 *
 * The payload below is copied from `script.bobi_cc_shabbat`: dotted item ids, a
 * `multi_select` device list whose choices live in `options`, and a temperature
 * per air conditioner that belongs to one profile.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ShabbatPage } from '@/pages/ShabbatPage';
import { splitProfile } from '@/features/shabbat/ProfileEditor';
import {
  makeConnection,
  makeManagementWith,
  makePreview,
  makeShabbat,
  makeStatus,
} from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';
import type { ManagedItem } from '@/types/api';

const DEVICES = [
  { value: 'dining', label: 'פינת אוכל', detail: null },
  { value: 'kitchen', label: 'מטבח', detail: null },
  { value: 'ac_salon', label: 'מזגן סלון', detail: null },
];

function item(overrides: Partial<ManagedItem>): ManagedItem {
  return {
    id: '', label: '', group: null, kind: 'text', value: null, display: null,
    description: null, risk: 'medium', controllable: true, operations: ['set'],
    primary_operation: 'set', run_operations: [], options: [], constraints: null,
    unavailable_reason: null, detail: {},
    ...overrides,
  };
}

const SNAPSHOT = {
  resource: 'shabbat', available: true, reason: null, writes_enabled: true, detail: {},
  groups: [
    { id: 'timing', label: 'זמנים', description: null, items: [
      item({ id: 'night_off_time', label: 'כיבוי ליל שבת', kind: 'time', value: '23:15' }),
      item({ id: 'extra_off_enabled', label: 'שעון כיבוי נוסף', kind: 'toggle', value: false }),
      item({ id: 'extra_off_time', label: 'שעת הכיבוי הנוסף', kind: 'time', value: '00:00' }),
    ]},
    { id: 'night_off', label: 'ליל שבת — כיבוי', description: null, items: [
      item({ id: 'profile.night_off.devices', label: 'מכשירים לכיבוי', kind: 'list',
             value: ['dining'], options: DEVICES }),
    ]},
    { id: 'pre_on', label: 'לפני שבת — הדלקה', description: null, items: [
      item({ id: 'profile.pre_on.devices', label: 'מכשירים להדלקה', kind: 'list',
             value: ['dining', 'ac_salon'], options: DEVICES }),
      item({ id: 'profile.pre_on.ac_salon', label: 'מזגן סלון', kind: 'number',
             value: 24, display: '24°' }),
      // A device with more than one setting names each one after itself, since
      // two items cannot share an id. All of them still belong to `ac_salon`.
      item({ id: 'profile.pre_on.ac_salon.hvac_mode', label: 'מצב הפעלה',
             kind: 'choice', value: 'cool', display: 'cool' }),
      item({ id: 'profile.pre_on.ac_salon.fan_mode', label: 'עוצמת מאוורר',
             kind: 'choice', value: 'auto', display: 'auto' }),
    ]},
    // A clock the household added. The bridge sends these after the four the
    // house already keeps, and it carries only a device list — its switch and
    // its hour are up in the timing group.
    { id: 'extra_off', label: 'שעון נוסף — כיבוי', description: null, items: [
      item({ id: 'profile.extra_off.devices', label: 'מכשירים לכיבוי', kind: 'list',
             value: [], options: [DEVICES[0]!] }),
    ]},
  ],
  items: [],
};

const ROUTES = {
  '/api/bobi/connection': makeConnection(),
  '/api/bobi/status': makeStatus(),
  '/api/auth/session': { authenticated: true, mode: 'home_assistant', role: 'owner' },
  '/api/bobi/shabbat': makeShabbat(),
  '/api/bobi/manage/contract': makeManagementWith('shabbat', { writes_enabled: true }),
  '/api/bobi/manage/shabbat/snapshot': SNAPSHOT,
  '/api/bobi/manage/shabbat/preview': makePreview(),
};

describe('splitting a profile', () => {
  it('tells the membership list from the per-device extras', () => {
    const parts = splitProfile(SNAPSHOT.groups[2]!.items);

    expect(parts.devices?.id).toBe('profile.pre_on.devices');
    expect([...parts.extras.keys()]).toEqual(['ac_salon']);
  });

  it('gathers every setting of one device under that device, not under each id', () => {
    const parts = splitProfile(SNAPSHOT.groups[2]!.items);

    // The failure this guards against is silent: keyed by the whole id, each
    // extra setting would land under a token no device has, and the sheet
    // would open empty rather than wrong.
    expect(parts.extras.get('ac_salon')?.map((i) => i.id)).toEqual([
      'profile.pre_on.ac_salon',
      'profile.pre_on.ac_salon.hvac_mode',
      'profile.pre_on.ac_salon.fan_mode',
    ]);
  });
});

describe('the Shabbat profile editor', () => {
  it('gives every device a chip rather than a dropdown', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    // One chip per device per profile that offers it — three profiles offer
    // this one — and not a single <select> among them.
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'פינת אוכל' })[0]).toBeEnabled(),
    );
    expect(screen.getAllByRole('button', { name: 'פינת אוכל' })).toHaveLength(3);
    expect(screen.queryByRole('combobox', { name: /מכשירים/ })).not.toBeInTheDocument();
  });

  it('marks the devices already in the profile', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('ליל שבת — כיבוי')).closest('li')!;
    await waitFor(() =>
      expect(within(card).getByRole('button', { name: 'פינת אוכל' })).toBeEnabled(),
    );
    expect(within(card).getByRole('button', { name: 'פינת אוכל' })).toHaveAttribute(
      'aria-pressed', 'true',
    );
    expect(within(card).getByRole('button', { name: 'מטבח' })).toHaveAttribute(
      'aria-pressed', 'false',
    );
  });

  it('shows what a device with extra settings is set to, on its chip', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('לפני שבת — הדלקה')).closest('li')!;
    expect(within(card).getByRole('button', { name: /מזגן סלון/ })).toHaveTextContent('24°');
  });

  it('opens a sheet for a device that has more to set, and a plain chip otherwise', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('לפני שבת — הדלקה')).closest('li')!;
    // A light has nothing else to say, so its chip is the control.
    expect(within(card).getByRole('button', { name: 'מטבח' })).not.toHaveAttribute(
      'aria-haspopup',
    );

    await userEvent.click(within(card).getByRole('button', { name: /מזגן סלון/ }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('switch', { name: /נכלל/ })).toBeInTheDocument();
    expect(within(sheet).getByDisplayValue('24')).toBeInTheDocument();
  });

  it('stages membership and asks for a preview rather than writing', async () => {
    const fetchMock = mockApi(ROUTES);
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('ליל שבת — כיבוי')).closest('li')!;
    await waitFor(() => expect(within(card).getByRole('button', { name: 'מטבח' })).toBeEnabled());
    await userEvent.click(within(card).getByRole('button', { name: 'מטבח' }));
    // Nothing has been sent yet.
    const before = fetchMock.mock.calls.filter(([u]) => String(u).includes('/preview'));
    expect(before).toHaveLength(0);

    await userEvent.click(within(card).getByRole('button', { name: 'בדוק שינוי במכשירים' }));
    const sent = fetchMock.mock.calls.find(([u]) => String(u).includes('/shabbat/preview'));
    expect(JSON.parse(String((sent?.[1] as RequestInit).body)).payload.value).toEqual([
      'dining',
      'kitchen',
    ]);
  });

  it('puts the profile s own time control on its card', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('ליל שבת — כיבוי')).closest('li')!;
    await waitFor(() =>
      expect(within(card).getByRole('combobox', { name: /— שעה/ })).toHaveValue('23'),
    );
  });
});

describe('what a session is allowed to do', () => {
  it('a viewer gets chips they cannot press', async () => {
    vi.stubGlobal('fetch', mockApi({
      ...ROUTES,
      '/api/auth/session': { authenticated: true, mode: 'home_assistant', role: 'viewer' },
    }));
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('ליל שבת — כיבוי')).closest('li')!;
    // The generic rows draw a padlock for this session; the chips must agree
    // with them rather than quietly offering what the backend would refuse.
    await waitFor(() =>
      expect(within(card).getByRole('button', { name: 'מטבח' })).toBeDisabled(),
    );
  });
});

describe('a time that belongs to a profile', () => {
  it('is not also drawn in the general timing card', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    // One control for one item. Two would let the same value be changed twice
    // by someone who thought they were looking at two settings.
    await waitFor(() =>
      expect(screen.getAllByRole('combobox', { name: 'כיבוי ליל שבת — שעה' })).toHaveLength(1),
    );
  });
});


describe('a Shabbat clock the household added', () => {
  it('carries its own switch and hour on its card, not in the list of times', async () => {
    vi.stubGlobal('fetch', mockApi(ROUTES));
    renderWithProviders(<ShabbatPage />);

    const card = (await screen.findByText('שעון נוסף — כיבוי')).closest('li')!;

    // Both controls belong to the clock, so both are inside its card...
    expect(within(card).getByText('שעון כיבוי נוסף')).toBeInTheDocument();
    expect(within(card).getByText('שעת הכיבוי הנוסף')).toBeInTheDocument();

    // ...and neither is left behind in the general timing list, where two
    // controls for one setting is how the same value gets changed twice by
    // someone who thought they were looking at two settings.
    expect(screen.getAllByText('שעון כיבוי נוסף')).toHaveLength(1);
    expect(screen.getAllByText('שעת הכיבוי הנוסף')).toHaveLength(1);

    // The clock that was already there is unaffected.
    expect(screen.getByText('כיבוי ליל שבת')).toBeInTheDocument();
  });
});
