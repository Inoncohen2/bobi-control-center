/**
 * The write flow, from a screen's point of view.
 *
 * The properties defended here are the ones a user's safety rests on: nothing
 * is written without a preview being shown and confirmed, a destructive change
 * needs more than a click, the result is reported honestly, and with management
 * off the controls simply are not there.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CapabilitiesPage } from '@/pages/CapabilitiesPage';
import { TasksPage } from '@/pages/TasksPage';
import {
  makeCapabilities,
  makeCommit,
  makeConnection,
  makeManagementOff,
  makeManagementOn,
  makePreview,
  makeStatus,
  makeTaskSnapshot,
  makeTasks,
} from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';

const BASE = {
  '/api/bobi/connection': makeConnection(),
  '/api/bobi/status': makeStatus(),
  '/api/bobi/tasks': makeTasks(),
  '/api/bobi/capabilities': makeCapabilities(),
};

/** Routes with the bridge present, and a preview/commit pair ready to serve. */
function managed(overrides: Record<string, unknown> = {}) {
  return {
    ...BASE,
    '/api/bobi/manage/contract': makeManagementOn(),
    '/api/bobi/manage/tasks/snapshot': makeTaskSnapshot(),
    '/api/bobi/manage/tasks/preview': makePreview(),
    '/api/bobi/manage/tasks/commit': makeCommit(),
    ...overrides,
  };
}

/** Every call the page made, as `[path, method]`. */
function calls(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.mock.calls.map(([input, init]) => [
    String(input).split('?')[0],
    (init as RequestInit | undefined)?.method ?? 'GET',
  ]);
}

// --- management off ---------------------------------------------------------
describe('with no Home Assistant write bridge', () => {
  it('says so and offers no controls', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ ...BASE, '/api/bobi/manage/contract': makeManagementOff() }),
    );
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText(/ניהול עדיין לא הופעל ב-Home Assistant/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'משימה חדשה' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'מחיקה' })).not.toBeInTheDocument();
  });

  it('leaves the master toggles read-only', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ ...BASE, '/api/bobi/manage/contract': makeManagementOff() }),
    );
    renderWithProviders(<CapabilitiesPage />);

    await screen.findByText('מתגים ראשיים');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.getAllByText('להפעלה או כיבוי: מסך ההגדרות').length).toBeGreaterThan(0);
  });

  it('keeps the capability master switches read-only even when it is on', async () => {
    // The AI master toggle and Fast Paths are outside this contract, so they
    // stay indicators no matter what the bridge declares.
    vi.stubGlobal('fetch', mockApi({ ...BASE, '/api/bobi/manage/contract': makeManagementOn() }));
    renderWithProviders(<CapabilitiesPage />);

    await screen.findByText('מתגים ראשיים');
    const switches = screen.queryAllByRole('switch');
    for (const control of switches) {
      // Only the contract's own features are operable.
      expect(['סיכום בוקר אוטומטי', 'מצב הבית האוטומטי']).toContain(
        control.getAttribute('aria-label'),
      );
    }
    expect(screen.getAllByText('להפעלה או כיבוי: מסך ההגדרות').length).toBeGreaterThan(0);
  });

  it('shows a feature whose state the bridge does not report as not operable', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        ...BASE,
        '/api/bobi/manage/contract': makeManagementOn({
          resources: [
            {
              id: 'features',
              label: 'תכונות',
              available: true,
              detail: null,
              operations: [{ id: 'set', label: 'הפעלה או כיבוי', destructive: false }],
              targets: [
                { id: 'morning_auto', label: 'סיכום בוקר אוטומטי', risk: 'low', enabled: null },
              ],
            },
          ],
        }),
      }),
    );
    renderWithProviders(<CapabilitiesPage />);

    expect(await screen.findByText('מצב לא ידוע')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});

// --- preview before anything -----------------------------------------------
describe('a change', () => {
  it('previews before it commits, and commits nothing on its own', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByRole('button', { name: 'משימה חדשה' }));
    await user.type(screen.getByLabelText('תוכן המשימה'), 'לקבוע תור לרופא');
    await user.click(screen.getByRole('button', { name: 'המשך לתצוגה מקדימה' }));

    // The preview dialog, clearly labelled as not having done anything.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('תצוגה מקדימה')).toBeInTheDocument();
    expect(within(dialog).getByText('עדיין לא בוצע דבר. אפשר לבטל.')).toBeInTheDocument();
    expect(within(dialog).getByText('הוספת משימה')).toBeInTheDocument();
    expect(within(dialog).getByText('לקבוע תור לרופא')).toBeInTheDocument();

    // One preview call, and no commit.
    const made = calls(fetchMock);
    expect(made).toContainEqual(['/api/bobi/manage/tasks/preview', 'POST']);
    expect(made).not.toContainEqual(['/api/bobi/manage/tasks/commit', 'POST']);
  });

  it('cannot be committed without pressing confirm', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByRole('button', { name: 'משימה חדשה' }));
    await user.type(screen.getByLabelText('תוכן המשימה'), 'לקבוע תור');
    await user.click(screen.getByRole('button', { name: 'המשך לתצוגה מקדימה' }));
    await screen.findByText('תצוגה מקדימה');

    // Cancelling is a way out that writes nothing.
    await user.click(screen.getByRole('button', { name: 'ביטול' }));

    expect(calls(fetchMock)).not.toContainEqual(['/api/bobi/manage/tasks/commit', 'POST']);
    expect(screen.queryByText('תצוגה מקדימה')).not.toBeInTheDocument();
  });

  it('commits only after confirmation, and reports the verified result', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByRole('button', { name: 'משימה חדשה' }));
    await user.type(screen.getByLabelText('תוכן המשימה'), 'לקבוע תור לרופא');
    await user.click(screen.getByRole('button', { name: 'המשך לתצוגה מקדימה' }));
    await screen.findByText('תצוגה מקדימה');

    await user.click(screen.getByRole('button', { name: 'בצע שינוי' }));

    // The dialog switches from preview to result, and says which happened.
    expect(await screen.findByText('ביצוע')).toBeInTheDocument();
    expect(screen.getByText('השינוי בוצע ואומת')).toBeInTheDocument();
    expect(calls(fetchMock)).toContainEqual(['/api/bobi/manage/tasks/commit', 'POST']);
  });

  it('sends the preview id it was given, never a bare request', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByRole('button', { name: 'משימה חדשה' }));
    await user.type(screen.getByLabelText('תוכן המשימה'), 'לקבוע תור');
    await user.click(screen.getByRole('button', { name: 'המשך לתצוגה מקדימה' }));
    await screen.findByText('תצוגה מקדימה');
    await user.click(screen.getByRole('button', { name: 'בצע שינוי' }));
    await screen.findByText('ביצוע');

    const commit = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/manage/tasks/commit'),
    );
    const body = JSON.parse(String((commit?.[1] as RequestInit).body));
    expect(body.preview_id).toBe('pv_test');
    expect(body.confirmed).toBe(true);
  });
});

// --- destructive ------------------------------------------------------------
describe('deleting a task', () => {
  const deletePreview = makePreview({
    operation: 'delete',
    resource_id: 'u-1',
    title: 'מחיקת משימה',
    destructive: true,
    warning: 'פעולה זו אינה הפיכה. המשימה תימחק ולא ניתן יהיה לשחזר אותה.',
    confirm_word: 'מחק',
    confirm_label: 'מחק משימה',
    changes: [{ label: 'משימה', before: 'לקבוע תור לרופא', after: null }],
  });

  it('warns, and refuses to commit until the word is typed', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(
      managed({ '/api/bobi/manage/tasks/preview': deletePreview }),
    );
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    const rows = await screen.findAllByRole('button', { name: 'מחיקה' });
    await user.click(rows[0] as HTMLElement);

    expect(await screen.findByText('מחיקת משימה')).toBeInTheDocument();
    expect(screen.getByText(/אינה הפיכה/)).toBeInTheDocument();

    const confirm = screen.getByRole('button', { name: 'מחק משימה' });
    expect(confirm).toBeDisabled();

    // A wrong word keeps it disabled.
    await user.type(screen.getByLabelText(/להמשך יש להקליד/), 'כן');
    expect(confirm).toBeDisabled();
    expect(calls(fetchMock)).not.toContainEqual(['/api/bobi/manage/tasks/commit', 'POST']);

    await user.clear(screen.getByLabelText(/להמשך יש להקליד/));
    await user.type(screen.getByLabelText(/להמשך יש להקליד/), 'מחק');
    await waitFor(() => expect(confirm).toBeEnabled());
  });
});

// --- honest results ---------------------------------------------------------
describe('the result', () => {
  async function commitWith(commitResponse: unknown) {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      mockApi(managed({ '/api/bobi/manage/tasks/commit': commitResponse })),
    );
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByRole('button', { name: 'משימה חדשה' }));
    await user.type(screen.getByLabelText('תוכן המשימה'), 'לקבוע תור');
    await user.click(screen.getByRole('button', { name: 'המשך לתצוגה מקדימה' }));
    await screen.findByText('תצוגה מקדימה');
    await user.click(screen.getByRole('button', { name: 'בצע שינוי' }));
    await screen.findByText('ביצוע');
  }

  it('does not claim success when verification failed', async () => {
    await commitWith(
      makeCommit({
        result: {
          status: 'committed_unverified',
          message: 'השינוי בוצע אך לא הצלחנו לאמת',
          resource_id: 'u-9',
          reason: 'verification_failed',
          verification: {
            verified: false,
            method: 'read_after_write',
            detail: 'לא הצלחנו לקרוא את הערך בחזרה',
          },
        },
      }),
    );

    expect(screen.getByText('השינוי בוצע אך לא הצלחנו לאמת')).toBeInTheDocument();
    expect(screen.queryByText('השינוי בוצע ואומת')).not.toBeInTheDocument();
  });

  it('says plainly when nothing happened', async () => {
    await commitWith(
      makeCommit({
        result: {
          status: 'failed',
          message: 'השינוי לא בוצע',
          resource_id: null,
          reason: 'stale_preview',
          verification: {
            verified: false,
            method: null,
            detail: 'המצב השתנה מאז התצוגה המקדימה. אפשר לנסות שוב.',
          },
        },
      }),
    );

    expect(screen.getByText('השינוי לא בוצע')).toBeInTheDocument();
  });
});

// --- the master write switch ------------------------------------------------
describe("Home Assistant's master write switch", () => {
  it('is presented as a disabled feature, not a connection failure', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ ...BASE, '/api/bobi/manage/contract': makeManagementOff() }),
    );
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText(/ניהול עדיין לא הופעל ב-Home Assistant/)).toBeInTheDocument();
    // Not the wording of a broken connection.
    expect(screen.queryByText(/לא הצלחתי לקבל נתונים/)).not.toBeInTheDocument();
    expect(screen.queryByText(/שגיאה/)).not.toBeInTheDocument();
    // The read-only screen still works.
    expect(screen.getByText('לקבוע תור לרופא')).toBeInTheDocument();
  });

  it('cannot be turned on from anywhere in the UI', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    await screen.findByRole('button', { name: 'משימה חדשה' });
    await user.click(screen.getByRole('button', { name: 'משימה חדשה' }));
    await user.type(screen.getByLabelText('תוכן המשימה'), 'לקנות חלב');
    await user.click(screen.getByRole('button', { name: 'המשך לתצוגה מקדימה' }));
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('button', { name: 'בצע שינוי' }));
    await screen.findByText('ביצוע');

    // Nothing the page sent, anywhere, tries to set the switch.
    for (const [, init] of fetchMock.mock.calls) {
      const body = String((init as RequestInit | undefined)?.body ?? '');
      expect(body).not.toContain('writes_enabled');
      expect(body).not.toContain('master');
    }
    // And no route exists for it.
    const paths = calls(fetchMock).map((entry) => entry[0] ?? '');
    expect(paths.some((path) => /writes|master|enable/.test(path))).toBe(false);
  });
});

// --- no raw Home Assistant identifiers --------------------------------------
describe('what the browser sends', () => {
  it('never names a todo or input_boolean service', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    const rows = await screen.findAllByRole('button', { name: 'מחיקה' });
    await user.click(rows[0] as HTMLElement);
    await screen.findByRole('dialog');

    for (const [input, init] of fetchMock.mock.calls) {
      const wire = `${String(input)} ${String((init as RequestInit | undefined)?.body ?? '')}`;
      expect(wire).not.toContain('todo.');
      expect(wire).not.toContain('input_boolean');
    }
  });

  it('sends the bridge uid as the target, not an entity id', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    const rows = await screen.findAllByRole('button', { name: 'מחיקה' });
    await user.click(rows[0] as HTMLElement);
    await screen.findByRole('dialog');

    const preview = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/manage/tasks/preview'),
    );
    const body = JSON.parse(String((preview?.[1] as RequestInit).body));
    expect(body.resource_id).toBe('u-1');
    expect(body.operation).toBe('delete');
  });

  it('lets the backend read the current state rather than claiming it', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(managed());
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<TasksPage />);

    // Completing a task sends the target and nothing else: `expected_status`
    // is the backend's to observe, so the screen cannot get it wrong.
    const checkboxes = await screen.findAllByRole('button', {
      name: 'סימון המשימה כבוצעה',
    });
    await user.click(checkboxes[0] as HTMLElement);
    await screen.findByRole('dialog');

    const preview = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/manage/tasks/preview'),
    );
    const body = JSON.parse(String((preview?.[1] as RequestInit).body));
    expect(body).toEqual({ operation: 'complete', resource_id: 'u-1' });
  });
});

// --- feature toggles --------------------------------------------------------
describe('a feature toggle', () => {
  it('previews the current and proposed state instead of switching', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...BASE,
      '/api/bobi/manage/contract': makeManagementOn(),
      '/api/bobi/manage/features/preview': makePreview({
        operation: 'set',
        resource_type: 'features',
        resource_id: 'morning_auto',
        title: 'הפעלת עיבוד תמונות',
        changes: [
          { label: 'תכונה', before: 'עיבוד תמונות', after: 'עיבוד תמונות' },
          { label: 'מצב', before: 'כבויה', after: 'פעילה' },
        ],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<CapabilitiesPage />);

    const toggles = await screen.findAllByRole('switch');
    await user.click(toggles[0] as HTMLElement);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('תצוגה מקדימה')).toBeInTheDocument();
    expect(within(dialog).getByText('כבויה')).toBeInTheDocument();
    expect(within(dialog).getByText('פעילה')).toBeInTheDocument();

    expect(calls(fetchMock)).not.toContainEqual([
      '/api/bobi/manage/features/commit',
      'POST',
    ]);
  });

  it('never writes to a Home Assistant entity id', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      ...BASE,
      '/api/bobi/manage/contract': makeManagementOn(),
      '/api/bobi/manage/tasks/snapshot': makeTaskSnapshot(),
      '/api/bobi/manage/features/preview': makePreview({ resource_type: 'features' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<CapabilitiesPage />);

    const toggles = await screen.findAllByRole('switch');
    await user.click(toggles[0] as HTMLElement);
    await screen.findByRole('dialog');

    const preview = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/manage/features/preview'),
    );
    const body = JSON.parse(String((preview?.[1] as RequestInit).body));
    // The contract's own feature id travels; the entity behind it never does.
    expect(body.resource_id).toBe('morning_auto');
    expect(JSON.stringify(body)).not.toContain('input_boolean');
    // The current state is the backend's to read, so the page does not send one.
    expect(body.payload).toEqual({ enabled: true });
  });
});
