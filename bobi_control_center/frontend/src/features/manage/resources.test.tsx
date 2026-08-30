/**
 * The contract-driven screens, from a household member's point of view.
 *
 * These defend the property that makes the whole design safe: **a control
 * appears only because the bridge said it could**. Every other guarantee in the
 * release rests on that one, and it is the guarantee most easily lost to a
 * refactor, because losing it looks like the page working better.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SettingsManagePage } from '@/pages/SettingsManagePage';
import { SystemPage } from '@/pages/SystemPage';
import { CamerasPage } from '@/pages/CamerasPage';
import { DevicesPage } from '@/pages/DevicesPage';
import { CalendarPage } from '@/pages/CalendarPage';
import { RulesManagePage } from '@/pages/RulesManagePage';
import { ListsPage } from '@/pages/ListsPage';
import {
  makeConnection,
  makeDevices,
  makeManagedItem,
  makeManagementOff,
  makeManagementOn,
  makeManagementWith,
  makeCommit,
  makePreview,
  makeResourceSnapshot,
  makeStatus,
} from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';

const BASE = {
  '/api/bobi/connection': makeConnection(),
  '/api/bobi/status': makeStatus(),
  // Ingress, which is what a household member on the panel gets. The tests
  // below are about what the *bridge* allows; the role tests at the end
  // override this to say what a *session* allows.
  '/api/auth/session': { authenticated: true, mode: 'home_assistant', role: 'owner' },
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
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
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
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  // `readonly` is what the backend returns when it could not work out how an
  // item is edited — an unrecognised kind becomes a reading rather than being
  // passed through, so that nobody is offered a field the bridge never said it
  // would accept. The screen used to fall through to a plain text box for it,
  // which handed back exactly the thing that kind exists to prevent: a
  // calendar event arrived `readonly` with `edit` advertised on it, and the
  // row drew a box you could type anything into and a button that sent it.
  it('renders a readonly kind as a reading, whatever the bridge advertised on it', async () => {
    stub(
      routes({
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              kind: 'readonly',
              value: '2026-09-02T18:00:00',
              display: '2026-09-02T18:00:00',
              controllable: true,
              operations: ['edit', 'delete'],
              primary_operation: 'edit',
            }),
          ],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText('סיכום בוקר אוטומטי')).toBeInTheDocument();
    expect(screen.getByText('2026-09-02T18:00:00')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'בדוק שינוי' })).not.toBeInTheDocument();
  });

  // The other half of the same fix. A scene is a reading — there is no value
  // to edit — but `activate` is a complete request on its own, and the scenes
  // screen exists to activate scenes. So a row with no editor offers the verbs
  // the contract marked as taking no payload, under the contract's own Hebrew
  // label. Which verbs those are is never decided here.
  it('offers a run button for a verb the contract said takes no payload', async () => {
    stub(
      routes({
        '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: true }, [
          { id: 'activate', label: 'הפעלת סצנה', destructive: false, valueless: true },
          { id: 'rename', label: 'שינוי שם', destructive: false, valueless: false },
          { id: 'delete', label: 'מחיקה', destructive: true, valueless: true },
        ]),
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              kind: 'readonly',
              value: 'ready',
              display: 'מוכן',
              controllable: true,
              operations: ['activate', 'rename', 'delete'],
              primary_operation: 'activate',
              run_operations: ['activate', 'delete'],
            }),
          ],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByRole('button', { name: 'הפעלת סצנה' })).toBeInTheDocument();
    // A rename needs a name, so it is not a button…
    expect(screen.queryByRole('button', { name: 'שינוי שם' })).not.toBeInTheDocument();
    // …and deleting takes no payload but is still not one tap away.
    expect(screen.queryByRole('button', { name: 'מחיקה' })).not.toBeInTheDocument();
    // The state stays visible beside it.
    expect(screen.getByText('מוכן')).toBeInTheDocument();
  });

  it('asks rather than acts when a run button is pressed', async () => {
    const fetchMock = stub({
      ...routes({
        '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: true }, [
          { id: 'activate', label: 'הפעלת סצנה', destructive: false, valueless: true },
        ]),
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              kind: 'readonly',
              value: 'ready',
              display: 'מוכן',
              controllable: true,
              operations: ['activate'],
              primary_operation: 'activate',
              run_operations: ['activate'],
            }),
          ],
        }),
      }),
    });
    renderWithProviders(<SettingsManagePage />);

    await userEvent.click(await screen.findByRole('button', { name: 'הפעלת סצנה' }));

    await waitFor(() =>
      expect(paths(fetchMock).some((path) => path.includes('/settings/preview'))).toBe(true),
    );
    expect(paths(fetchMock).some((path) => path.includes('/commit'))).toBe(false);
  });

  it('offers no run button while the master write switch is off', async () => {
    stub(
      routes({
        '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: false }, [
          { id: 'activate', label: 'הפעלת סצנה', destructive: false, valueless: true },
        ]),
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [
            makeManagedItem({
              kind: 'readonly',
              value: 'ready',
              display: 'מוכן',
              controllable: true,
              operations: ['activate'],
              primary_operation: 'activate',
              run_operations: ['activate'],
            }),
          ],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    await screen.findByText('סיכום בוקר אוטומטי');
    expect(screen.queryByRole('button', { name: 'הפעלת סצנה' })).not.toBeInTheDocument();
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
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});

describe('a family whose commit bridge has not shipped', () => {
  it('shows the values and offers nothing to press', async () => {
    stub(
      routes({
        '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: true }, []),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    // The values are all there…
    expect(await screen.findByText('סיכום בוקר אוטומטי')).toBeInTheDocument();
    // …and the reason there is no save button is stated, not left to guess.
    expect(screen.getByText(/קריאה בלבד/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /כבה|הפעל/ })).not.toBeInTheDocument();
  });

  it('offers no control even when the item says it is controllable', async () => {
    stub(
      routes({
        '/api/bobi/manage/contract': makeManagementWith('settings', { writes_enabled: true }, []),
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
          items: [makeManagedItem({ controllable: true, operations: ['set'] })],
        }),
      }),
    );
    renderWithProviders(<SettingsManagePage />);

    await screen.findByText('סיכום בוקר אוטומטי');
    // The item says yes; the family has no commit bridge. Both must agree.
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});

describe('a control the bridge did advertise', () => {
  it('asks for a preview and writes nothing by itself', async () => {
    const fetchMock = stub(routes());
    renderWithProviders(<SettingsManagePage />);

    await userEvent.click(await screen.findByRole('switch'));

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

  it('shows the picture through this app, naming no entity and carrying no token', async () => {
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

    const frame = await screen.findByRole('img', { name: /תמונה חיה/ });
    const src = frame.getAttribute('src') ?? '';

    // The canonical id, and only that. An entity id or a token in this URL
    // would mean the browser had been handed one.
    expect(src).toContain('/api/bobi/cameras/cam_lia/snapshot');
    expect(src).not.toContain('camera.');
    expect(src).not.toContain('token');
  });

  it('says a camera is unreachable rather than showing a broken picture', async () => {
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
            value: 'unavailable',
            display: 'לא זמינה',
            controllable: false,
            operations: [],
            detail: { device_class: 'camera' },
          }),
        ],
      }),
    });
    renderWithProviders(<CamerasPage />);

    // The live camera answers 500 because it is unplugged, which in a browser
    // is an image that fails to load. That has to read as a fact about the
    // camera, not as a bug in the app.
    const frame = await screen.findByRole('img', { name: /תמונה חיה/ });
    fireEvent.error(frame);

    expect(await screen.findByText('המצלמה אינה זמינה כרגע')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /תמונה חיה/ })).not.toBeInTheDocument();
    // Still nothing to press that reaches the camera.
    expect(screen.queryByRole('button', { name: /הפעל|כבה/ })).not.toBeInTheDocument();
  });

  it('offers no power control even if the contract marks the camera controllable', async () => {
    // The one case where trusting a flag is not enough: by the time you could
    // switch a camera back off, somebody has been recorded.
    stub({
      ...BASE,
      '/api/bobi/manage/contract': makeManagementWith('devices', { writes_enabled: true }),
      '/api/bobi/manage/devices/snapshot': makeResourceSnapshot({
        resource: 'devices',
        items: [
          makeManagedItem({
            id: 'cam_lia',
            label: 'מצלמת ליה',
            kind: 'toggle',
            value: false,
            controllable: true,
            operations: ['set'],
            detail: { device_class: 'camera' },
          }),
        ],
      }),
    });
    renderWithProviders(<CamerasPage />);

    expect(await screen.findByText('מצלמת ליה')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /הפעל|כבה/ })).not.toBeInTheDocument();
  });
});

describe('what the session is allowed to do', () => {
  /** The session endpoint answers with a role; everything else stays the same. */
  function withRole(role: string, overrides: Record<string, unknown> = {}) {
    return stub({
      ...routes(overrides),
      '/api/auth/session': { authenticated: true, mode: 'external', role },
    });
  }

  it('an operator gets ordinary controls', async () => {
    withRole('operator');
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByRole('switch')).toBeInTheDocument();
  });

  it('a viewer gets none, and is told why', async () => {
    withRole('viewer');
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText('סיכום בוקר אוטומטי')).toBeInTheDocument();
    expect(await screen.findByText(/אין גישה לשינוי/)).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('an operator gets no control over a high-risk row', async () => {
    withRole('operator', {
      '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
        items: [makeManagedItem({ risk: 'high' })],
      }),
    });
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByText(/אין גישה לשינוי/)).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('an admin does', async () => {
    withRole('admin', {
      '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
        items: [makeManagedItem({ risk: 'high' })],
      }),
    });
    renderWithProviders(<SettingsManagePage />);

    expect(await screen.findByRole('switch')).toBeInTheDocument();
  });

  it('an unknown role is treated as the weakest one', async () => {
    withRole('superuser');
    renderWithProviders(<SettingsManagePage />);

    await screen.findByText('סיכום בוקר אוטומטי');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});

/**
 * The calendar, whose one write is creating.
 *
 * Home Assistant publishes no service that deletes or updates a calendar event,
 * so the bridge advertises nothing on an event and the screen offers no control
 * on one. Adding is the write that exists — and the form appears only because
 * the contract named `add` and said which calendars it may be added to.
 */
describe('the calendar', () => {
  const WRITABLE = [
    { id: 'user_1', label: 'ינון', risk: null, enabled: null },
    { id: 'user_2', label: 'הודיה', risk: null, enabled: null },
  ];

  const calendarRoutes = (
    // What the *API* serves, which is not quite what Home Assistant sent: the
    // backend translates the bridge's `add` into this application's `create`
    // before a screen ever sees it.
    operations = [{ id: 'create', label: 'הוספת אירוע', destructive: false, valueless: false }],
    targets = WRITABLE,
  ) => ({
    ...BASE,
    '/api/bobi/manage/contract': makeManagementWith(
      'calendar',
      { writes_enabled: true },
      operations,
      targets,
    ),
    '/api/bobi/manage/calendar/snapshot': makeResourceSnapshot({
      resource: 'calendar',
      groups: [],
      items: [],
    }),
    '/api/bobi/manage/calendar/preview': makePreview(),
  });

  it('offers a form for the one write Home Assistant supports', async () => {
    stub(calendarRoutes());
    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText('אירוע חדש')).toBeInTheDocument();
  });

  it('draws no form when the contract did not name the operation', async () => {
    // A snapshot bridge whose commit bridge has not shipped: readable, no button.
    stub(calendarRoutes([]));
    renderWithProviders(<CalendarPage />);

    await screen.findByText('קריאה בלבד');
    expect(screen.queryByText('אירוע חדש')).not.toBeInTheDocument();
  });

  it('draws no form when the contract named no calendar to write to', async () => {
    stub(calendarRoutes(undefined, []));
    renderWithProviders(<CalendarPage />);

    await screen.findByText('יומן');
    expect(screen.queryByText('אירוע חדש')).not.toBeInTheDocument();
  });

  it('sends what was typed, and only once the button is pressed', async () => {
    const fetchMock = stub(calendarRoutes());
    renderWithProviders(<CalendarPage />);

    await screen.findByText('אירוע חדש');
    await userEvent.type(screen.getByLabelText('כותרת'), 'רופא שיניים');
    await userEvent.type(screen.getByLabelText('תאריך'), '2026-09-10');
    await userEvent.type(screen.getByLabelText('משעה'), '09:00');
    await userEvent.type(screen.getByLabelText('עד שעה'), '10:00');

    // Typing is not a request to change anything.
    expect(paths(fetchMock).some((path) => path.endsWith('/calendar/preview'))).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'בדוק שינוי' }));

    await waitFor(() =>
      expect(paths(fetchMock).some((path) => path.endsWith('/calendar/preview'))).toBe(true),
    );
    const call = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/calendar/preview'),
    );
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body.operation).toBe('create');
    expect(body.resource_id).toBeNull();
    expect(body.payload).toMatchObject({
      user_id: 'user_1',
      summary: 'רופא שיניים',
      start: '2026-09-10T09:00:00',
      end: '2026-09-10T10:00:00',
    });
  });
});

/**
 * The switch on a device card.
 *
 * The card is the point: turning a light on used to mean opening the page,
 * scrolling past the whole catalogue to a second list, finding the same light
 * again by name, and pressing there. What must not change is what the switch
 * means — it asks, it does not act.
 */
describe('a device card', () => {
  const KITCHEN = makeManagedItem({
    id: 'kitchen',
    label: 'אור מטבח', // the same `canonical` the catalogue names it by
    kind: 'toggle',
    value: false,
    risk: 'medium',
    controllable: true,
    operations: ['power'],
    primary_operation: 'power',
  });

  const deviceRoutes = (item = KITCHEN, writes = true, overrides = {}) => ({
    ...BASE,
    '/api/bobi/devices': makeDevices(),
    '/api/bobi/manage/contract': makeManagementWith('devices', { writes_enabled: writes }, [
      { id: 'power', label: 'הדלקה או כיבוי', destructive: false, valueless: false },
    ]),
    '/api/bobi/manage/devices/snapshot': makeResourceSnapshot({
      resource: 'devices',
      items: [item],
      groups: [{ id: 'devices', label: 'מכשירים', description: null, items: [item] }],
    }),
    '/api/bobi/manage/devices/preview': makePreview(),
    '/api/bobi/manage/devices/commit': makeCommit(),
    ...overrides,
  });

  it('puts a switch on the card, matched to the catalogue row', async () => {
    stub(deviceRoutes());
    renderWithProviders(<DevicesPage />);

    const toggle = await screen.findByRole('switch', { name: 'אור מטבח' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  // A switch on the catalogue applies at once now: flipping a light is not a
  // decision anybody wants read back to them first. What must not change is
  // that it still goes *through* a preview — the token, the expected state and
  // every published limit are checked there — and that a change the backend
  // wants confirmed still stops and asks.
  it('applies at once, and still through a preview', async () => {
    const fetchMock = stub(deviceRoutes());
    renderWithProviders(<DevicesPage />);

    await userEvent.click(await screen.findByRole('switch', { name: 'אור מטבח' }));

    await waitFor(() =>
      expect(paths(fetchMock).some((path) => path.endsWith('/devices/commit'))).toBe(true),
    );
    const call = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/devices/preview'),
    );
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toMatchObject({
      operation: 'power',
      resource_id: 'kitchen',
      payload: { value: true },
    });
    // The commit quotes the preview it was given, never the client's wish.
    const committed = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/devices/commit'),
    );
    expect(JSON.parse(String(committed?.[1]?.body)).preview_id).toBe('pv_test');
    // …and no dialog was put in the way.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('moves the switch the moment it is pressed, before anything has landed', async () => {
    // The press used to wait on a preview, a commit and a fresh snapshot —
    // three round trips — so from a phone the switch sat still and the tap
    // felt lost. It now shows the request immediately. This holds the commit
    // open so "immediately" is the only thing that could have moved it.
    let releaseCommit: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      releaseCommit = resolve;
    });

    const inner = mockApi(deviceRoutes());
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/devices/commit')) await held;
      return inner(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<DevicesPage />);

    const toggle = await screen.findByRole('switch', { name: 'אור מטבח' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    await userEvent.click(toggle);

    // Nothing has been confirmed by the house, and the switch has already moved.
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'אור מטבח' })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
    releaseCommit?.();
  });

  it('leaves every other switch alone while one is applying', async () => {
    // `pending` pulses the switch and refuses further presses. It used to be
    // handed the whole page's change state, so turning on one light made every
    // switch on the screen blink and go unpressable at once.
    const SALON = makeManagedItem({
      id: 'salon',
      label: 'מזגן סלון', // matches a second device in the catalogue fixture
      kind: 'toggle',
      value: false,
      risk: 'medium',
      controllable: true,
      operations: ['power'],
      primary_operation: 'power',
    });
    const both = {
      ...deviceRoutes(),
      '/api/bobi/manage/devices/snapshot': makeResourceSnapshot({
        resource: 'devices',
        items: [KITCHEN, SALON],
        groups: [
          {
            id: 'devices',
            label: 'מכשירים',
            description: null,
            items: [KITCHEN, SALON],
          },
        ],
      }),
    };

    let releaseCommit: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      releaseCommit = resolve;
    });
    const inner = mockApi(both);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/devices/commit')) await held;
      return inner(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<DevicesPage />);

    const kitchen = await screen.findByRole('switch', { name: 'אור מטבח' });
    const salon = await screen.findByRole('switch', { name: 'מזגן סלון' });
    await userEvent.click(kitchen);

    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'אור מטבח' })).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );

    // The one that was not pressed has not moved and is still usable.
    expect(salon).toHaveAttribute('aria-checked', 'false');
    expect(salon).toBeEnabled();
    releaseCommit?.();
  });

  it('shows no dialog *while* the switch is still applying', async () => {
    // The assertion above only looks once the gesture has finished, so it held
    // even while the dialog was opening mid-flight and closing itself on
    // success: `startAndApply` sets a preview one tick before it commits, and
    // the dialog opened on that. On a phone over Cloudflare that is a modal
    // reading "עדיין לא בוצע דבר" sitting over a spinner — for a light switch.
    // So this holds the commit open and looks while it is in flight.
    let releaseCommit: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      releaseCommit = resolve;
    });

    const routes = deviceRoutes();
    const inner = mockApi(routes);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/devices/commit')) await held;
      return inner(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<DevicesPage />);

    await userEvent.click(await screen.findByRole('switch', { name: 'אור מטבח' }));

    // The commit is in flight and deliberately unresolved.
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => String(input).endsWith('/devices/commit')),
      ).toBe(true),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText('עדיין לא בוצע דבר. אפשר לבטל.')).not.toBeInTheDocument();

    releaseCommit?.();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('still stops and asks when the backend calls the change destructive', async () => {
    const fetchMock = stub(
      deviceRoutes(KITCHEN, true, {
        '/api/bobi/manage/devices/preview': makePreview({
          destructive: true,
          confirm_word: 'מחק',
        }),
      }),
    );
    renderWithProviders(<DevicesPage />);

    await userEvent.click(await screen.findByRole('switch', { name: 'אור מטבח' }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(paths(fetchMock).some((path) => path.endsWith('/devices/commit'))).toBe(false);
  });

  it('draws no switch while the master write switch is off', async () => {
    stub(deviceRoutes(KITCHEN, false));
    renderWithProviders(<DevicesPage />);

    await screen.findByText('אור מטבח');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('draws no switch for an item the bridge did not mark controllable', async () => {
    stub(deviceRoutes({ ...KITCHEN, controllable: false }));
    renderWithProviders(<DevicesPage />);

    await screen.findByText('אור מטבח');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('refuses to guess when two switchable devices share a name', async () => {
    // A name is weaker than an id. Matching neither is the safe answer: a
    // missing switch is a bad afternoon, the wrong light going off is worse.
    const twin = { ...KITCHEN, id: 'kitchen_2' };
    stub({
      ...deviceRoutes(),
      '/api/bobi/manage/devices/snapshot': makeResourceSnapshot({
        resource: 'devices',
        items: [KITCHEN, twin],
        groups: [
          { id: 'devices', label: 'מכשירים', description: null, items: [KITCHEN, twin] },
        ],
      }),
    });
    renderWithProviders(<DevicesPage />);

    await screen.findByText('אור מטבח');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});

// `<input type="time">` renders its text in the browser's UI language, which no
// page setting reaches: with the context locale forced to he-IL, Chromium still
// drew "11:30 PM" on a Hebrew right-to-left screen. So the clock is built here
// rather than borrowed, and these hold it to a 24-hour reading.
describe('a time the bridge published', () => {
  const timeRoutes = (value: string) =>
    routes({
      '/api/bobi/manage/settings/snapshot': makeResourceSnapshot({
        items: [
          makeManagedItem({
            id: 'night_off_time',
            label: 'כיבוי ליל שבת',
            kind: 'time',
            value,
            display: value,
          }),
        ],
      }),
    });

  it('is edited on a 24-hour clock, with no AM or PM anywhere', async () => {
    stub(timeRoutes('23:30'));
    renderWithProviders(<SettingsManagePage />);

    const hours = await screen.findByRole('combobox', { name: 'כיבוי ליל שבת — שעה' });
    const minutes = screen.getByRole('combobox', { name: 'כיבוי ליל שבת — דקות' });
    expect(hours).toHaveValue('23');
    expect(minutes).toHaveValue('30');
    // 23 exists as an hour, which a 12-hour control could not offer.
    expect(screen.queryByText(/AM|PM/)).not.toBeInTheDocument();
  });

  it('asks for a preview only once a whole time has been chosen', async () => {
    const fetchMock = stub(timeRoutes('23:30'));
    renderWithProviders(<SettingsManagePage />);

    const hours = await screen.findByRole('combobox', { name: 'כיבוי ליל שבת — שעה' });
    await userEvent.selectOptions(hours, '07');
    await userEvent.click(screen.getByRole('button', { name: 'בדוק שינוי' }));

    await waitFor(() =>
      expect(paths(fetchMock).some((path) => path.includes('/settings/preview'))).toBe(true),
    );
    const sent = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/settings/preview'),
    );
    expect(JSON.parse(String((sent?.[1] as RequestInit).body)).payload.value).toBe('07:30');
  });
});

// --- creating a smart rule --------------------------------------------------
describe('the rules screen', () => {
  /** The contract this house publishes for `rules` since 2026-08-29. */
  const RULE_OPERATIONS = [
    { id: 'create', label: 'יצירת אוטומציה', destructive: false, valueless: false },
    { id: 'enable', label: 'הפעלה', destructive: false, valueless: true },
    { id: 'disable', label: 'השבתה', destructive: false, valueless: true },
    { id: 'delete', label: 'מחיקה', destructive: true, valueless: true },
  ];

  function rulesRoutes(operations = RULE_OPERATIONS) {
    return {
      ...BASE,
      '/api/bobi/manage/contract': makeManagementWith(
        'rules',
        { writes_enabled: true },
        operations,
      ),
      '/api/bobi/manage/rules/snapshot': makeResourceSnapshot({ items: [] }),
      '/api/bobi/manage/rules/preview': makePreview(),
    };
  }

  it('offers the form the contract declares', async () => {
    stub(rulesRoutes());
    renderWithProviders(<RulesManagePage />);

    expect(await screen.findByText('אוטומציה חדשה')).toBeInTheDocument();
    expect(screen.getByLabelText('מה בובי יעשה')).toBeInTheDocument();
  });

  it('draws no form when the contract does not declare creating one', async () => {
    // This is what the house published until 2026-08-29: `rule_create` sat in
    // `not_supported` and the commit script had no create branch. A screen that
    // offered the form anyway would collect a whole rule and then be refused.
    stub(rulesRoutes(RULE_OPERATIONS.filter((operation) => operation.id !== 'create')));
    renderWithProviders(<RulesManagePage />);

    // Wait for the *snapshot* to have rendered, not merely the page title: the
    // title is there on the first paint, so asserting against it proved
    // nothing — the form was still absent because nothing had loaded yet.
    expect(await screen.findByText('אין אוטומציות.')).toBeInTheDocument();
    expect(screen.queryByText('אוטומציה חדשה')).not.toBeInTheDocument();
  });

  it('will not send a weekly rule with no day chosen', async () => {
    // The engine needs the *next* run, not a time of day, and it cannot work
    // one out without days. Leaving the button live would send a rule the
    // bridge refuses after the person had filled the whole form in.
    const user = userEvent.setup();
    stub(rulesRoutes());
    renderWithProviders(<RulesManagePage />);

    await screen.findByText('אוטומציה חדשה');
    await user.type(screen.getByLabelText('שם'), 'בוקר');
    await user.type(screen.getByLabelText('מה בובי יעשה'), 'תדליק את הדוד');
    await user.selectOptions(screen.getByLabelText('סוג'), 'weekly');
    await user.type(screen.getByLabelText('שעה'), '06:30');

    const check = screen.getByRole('button', { name: 'בדוק שינוי' });
    expect(check).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'ג׳' }));
    expect(check).toBeEnabled();
  });
});

// --- the household's lists --------------------------------------------------
describe('the lists screen', () => {
  function listRoutes(snapshot?: Parameters<typeof makeResourceSnapshot>[0]) {
    return {
      ...BASE,
      '/api/bobi/manage/contract': makeManagementWith('lists', { writes_enabled: true }, []),
      '/api/bobi/manage/lists/snapshot':
        snapshot === undefined
          ? makeResourceSnapshot({
              groups: [
                {
                  id: 'shopping',
                  label: 'קניות',
                  description: null,
                  items: [
                    makeManagedItem({ id: 'a', label: 'חלב', kind: 'toggle', value: false }),
                    makeManagedItem({ id: 'b', label: 'לחם', kind: 'toggle', value: true }),
                  ],
                },
                { id: 'family', label: 'משפחה', description: null, items: [] },
              ],
              items: [],
            })
          : makeResourceSnapshot(snapshot),
    };
  }

  it('shows each list with the things on it', async () => {
    stub(listRoutes());
    renderWithProviders(<ListsPage />);

    expect(await screen.findByText('קניות')).toBeInTheDocument();
    expect(screen.getByText('חלב')).toBeInTheDocument();
    expect(screen.getByText('לחם')).toBeInTheDocument();
  });

  it('counts what is still open, not what is on the list', async () => {
    // Two items, one already bought. A badge reading "2" next to a list with
    // one thing left to buy is worse than no badge at all.
    stub(listRoutes());
    renderWithProviders(<ListsPage />);

    await screen.findByText('קניות');
    const shopping = screen.getByRole('heading', { name: 'קניות' }).closest('section');
    expect(shopping).not.toBeNull();
    expect(within(shopping as HTMLElement).getByText('1')).toBeInTheDocument();
  });

  it('says something human when a list is empty', async () => {
    // And never a bare "0": an empty family list is the normal case, not a
    // fault, so the count is withheld and the tile explains itself.
    stub(listRoutes());
    renderWithProviders(<ListsPage />);

    expect(await screen.findByText('הרשימה ריקה.')).toBeInTheDocument();
    const family = screen.getByRole('heading', { name: 'משפחה' }).closest('section');
    expect(within(family as HTMLElement).queryByText('0')).not.toBeInTheDocument();
  });

  it('renders a list it has never heard of rather than dropping it', async () => {
    // The colours are keyed on the bridge's group id. A household that adds a
    // list this application has no entry for must still see it.
    stub(
      listRoutes({
        groups: [
          {
            id: 'garden',
            label: 'גינה',
            description: null,
            items: [makeManagedItem({ id: 'c', label: 'לזרוע בזיליקום', kind: 'toggle', value: false })],
          },
        ],
        items: [],
      }),
    );
    renderWithProviders(<ListsPage />);

    expect(await screen.findByText('גינה')).toBeInTheDocument();
    expect(screen.getByText('לזרוע בזיליקום')).toBeInTheDocument();
  });
});
