/**
 * Screen-level tests for the real-data pages.
 *
 * Two things every screen must prove: it renders bridge data correctly, and it
 * offers no write control in Phase 2.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CapabilitiesPage } from './CapabilitiesPage';
import { DashboardPage } from './DashboardPage';
import { DevicesPage } from './DevicesPage';
import { DiagnosticsPage } from './DiagnosticsPage';
import { RulesPage } from './RulesPage';
import { ShabbatPage } from './ShabbatPage';
import { TasksPage } from './TasksPage';
import { UsersPage } from './UsersPage';
import {
  makeCapabilities,
  makeConnection,
  makeDevices,
  makeDiagnostics,
  makeRules,
  makeShabbat,
  makeStatus,
  makeTasks,
  makeUsers,
} from '@/test/fixtures';
import { mockApi, mockDisconnected, renderWithProviders } from '@/test/utils';

const ALL_ROUTES = {
  '/api/bobi/connection': makeConnection(),
  '/api/bobi/status': makeStatus(),
  '/api/bobi/devices': makeDevices(),
  '/api/bobi/capabilities': makeCapabilities(),
  '/api/bobi/users': makeUsers(),
  '/api/bobi/shabbat': makeShabbat(),
  '/api/bobi/rules': makeRules(),
  '/api/bobi/tasks': makeTasks(),
  '/api/bobi/diagnostics': makeDiagnostics(),
};

// --- dashboard --------------------------------------------------------------
describe('DashboardPage', () => {
  it('renders health, counts and open issues from the bridge', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText('WhatsApp')).toBeInTheDocument();
    expect(screen.getByText('מכשירים')).toBeInTheDocument();
    expect(screen.getByText('18')).toBeInTheDocument();
    expect(await screen.findByText('מצלמת ליה אינה זמינה')).toBeInTheDocument();
  });

  it('shows the sections the bridge reports beyond the health row', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DashboardPage />);

    // WhatsApp, AI and configuration health, derived server-side.
    expect(await screen.findByText('WhatsApp')).toBeInTheDocument();
    expect(screen.getByText('בינה מלאכותית')).toBeInTheDocument();
    expect(screen.getByText('תצורה')).toBeInTheDocument();

    // Fast paths, active users and the feature toggles.
    expect(screen.getByText('מסלולים מהירים')).toBeInTheDocument();
    expect(screen.getByText('lighting')).toBeInTheDocument();
    expect(screen.getByText('משתמשי הבית')).toBeInTheDocument();
    expect(screen.getByText('פעילים')).toBeInTheDocument();
    expect(screen.getByText('שעון שבת')).toBeInTheDocument();
    expect(screen.getByText('עיבוד תמונות')).toBeInTheDocument();
  });

  it('summarises the feature toggles and says where they are changed', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DashboardPage />);

    await screen.findByText('שעון שבת');
    // The dashboard reports; it does not operate. It used to say editing was
    // coming in a later phase, which sent people away from a control that
    // already existed on the settings screen.
    expect(screen.getByText('להפעלה או כיבוי: מסך ההגדרות')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('states the resolved overall health', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText('בובי תקין')).toBeInTheDocument();
    expect(screen.getByText('כל הרכיבים הידועים תקינים')).toBeInTheDocument();
  });

  it('renders unknown health as unknown, never as a failure', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        ...ALL_ROUTES,
        '/api/bobi/status': makeStatus({
          health: { status: 'unknown', ok: null, reason: 'הגשר לא דיווח על מצב כללי' },
          ok: null,
        }),
      }),
    );
    renderWithProviders(<DashboardPage />);

    const banner = await screen.findByText('מצב בובי לא ידוע');
    // Muted, not the red/amber of a real fault.
    const badge = banner.closest('span');
    expect(badge?.className).not.toMatch(/rose|amber/);
    expect(screen.queryByText('בובי לא תקין')).not.toBeInTheDocument();
  });

  it('keeps entity ids behind the technical disclosure', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DashboardPage />);

    await screen.findByText('מצלמת ליה אינה זמינה');
    const disclosure = screen.getAllByText('פרטים טכניים')[0];
    expect(disclosure?.closest('details')?.open).toBeFalsy();
  });

  it('celebrates when nothing needs attention', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        ...ALL_ROUTES,
        '/api/bobi/diagnostics': makeDiagnostics({ issues: [], issue_count: 0, ok: true }),
      }),
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText('לא נמצאו תקלות 🎉')).toBeInTheDocument();
  });

  it('says plainly when Home Assistant cannot be reached', async () => {
    vi.stubGlobal('fetch', mockDisconnected());
    renderWithProviders(<DashboardPage />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('לא הצלחתי לקבל נתונים מ-Home Assistant');

    // The status code belongs in the collapsed technical section, never in the
    // message the user reads first.
    const details = alert.querySelector('details');
    expect(details?.open).toBeFalsy();
    const visible = alert.textContent?.replace(details?.textContent ?? '', '') ?? '';
    expect(visible).not.toMatch(/Traceback|502/);
  });
});

// --- devices ----------------------------------------------------------------
describe('DevicesPage', () => {
  it('shows canonical names grouped by area, not entity ids', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    expect(await screen.findByText('אור מטבח')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /סלון/ })).toBeInTheDocument();
    // The entity id must not be on the card.
    expect(screen.queryByText(/light\.demo_kitchen/)).not.toBeInTheDocument();
  });

  it('reveals entity_id and handler only under the technical disclosure', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    await user.click(await screen.findByText('אור מטבח'));

    const summary = await screen.findByText('פרטים טכניים');
    expect(summary.closest('details')?.open).toBeFalsy();
    expect(screen.getByText('light.demo_kitchen')).toBeInTheDocument();
    expect(screen.getByText('lighting_handler')).toBeInTheDocument();
  });

  it('shows the domain-specific limits the bridge sends', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    await user.click(await screen.findByText('מזגן סלון'));

    expect(await screen.findByText('טווחים ואפשרויות')).toBeInTheDocument();
    expect(screen.getByText('טמפרטורה מינימלית')).toBeInTheDocument();
    expect(screen.getByText('16')).toBeInTheDocument();
    expect(screen.getByText('עוצמות מאוורר')).toBeInTheDocument();
    expect(screen.getByText('low · high')).toBeInTheDocument();
  });

  it('shows the aliases Bobi understands', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    await user.click(await screen.findByText('אור מטבח'));
    expect(await screen.findByText('כינויים שבובי מבין')).toBeInTheDocument();
    expect(screen.getByText('האור במטבח')).toBeInTheDocument();
  });

  it('filters by alias as the user types', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    await screen.findByText('אור מטבח');
    await user.type(screen.getByLabelText('חיפוש מכשירים'), 'המזגן בסלון');

    expect(await screen.findByText('מזגן סלון')).toBeInTheDocument();
    expect(screen.queryByText('אור מטבח')).not.toBeInTheDocument();
  });

  it('requests a new scope from the bridge when one is chosen', async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi(ALL_ROUTES);
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<DevicesPage />);

    await screen.findByText('אור מטבח');
    await user.click(screen.getByRole('button', { name: 'מיזוג' }));

    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes('scope=climate')),
    ).toBe(true);
  });

  it('marks an unavailable device without relying on colour', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    expect(await screen.findByText('מצלמת ליה')).toBeInTheDocument();
    expect(screen.getByText('לא זמין')).toBeInTheDocument();
  });

  it('offers no control over a device', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DevicesPage />);

    await screen.findByText('אור מטבח');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    for (const button of screen.getAllByRole('button')) {
      expect(button.textContent ?? '').not.toMatch(/הדלק|כבה|הפעל/);
    }
  });
});

// --- capabilities -----------------------------------------------------------
describe('CapabilitiesPage', () => {
  it('renders the registry dynamically, grouped by its own groups', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<CapabilitiesPage />);

    expect(await screen.findByText('שליטה בתאורה')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'שליטה בבית' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'בינה מלאכותית' })).toBeInTheDocument();
    expect(screen.getByText('„תדליק את אור הסלון”')).toBeInTheDocument();
    expect(screen.getByText('סיכון גבוה')).toBeInTheDocument();
  });

  it('does not discard a capability it has never seen before', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        ...ALL_ROUTES,
        '/api/bobi/capabilities': makeCapabilities({
          capabilities: [
            {
              id: 'brand_new',
              handler: 'future_handler',
              local: true,
              local_after_parse: false,
              risk: 'low',
              label: 'יכולת עתידית',
              example: 'משהו חדש לגמרי',
              group: null,
              some_unknown_field: 'kept',
            } as never,
          ],
        }),
      }),
    );
    renderWithProviders(<CapabilitiesPage />);

    expect(await screen.findByText('יכולת עתידית')).toBeInTheDocument();
    // No group means it still gets rendered, under a fallback heading.
    expect(screen.getByRole('heading', { name: 'יכולות נוספות' })).toBeInTheDocument();
  });

  it('keeps the handler out of the card and inside Advanced', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<CapabilitiesPage />);

    await screen.findByText('שליטה בתאורה');
    expect(screen.queryByText('lighting_handler')).not.toBeInTheDocument();

    await user.click(screen.getByText('שליטה בתאורה'));
    const summary = await screen.findByText('פרטים טכניים');
    expect(summary.closest('details')?.open).toBeFalsy();
    expect(screen.getByText('lighting_handler')).toBeInTheDocument();
  });

  it('renders master toggles as read-only', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<CapabilitiesPage />);

    expect(await screen.findByText('מתגים ראשיים')).toBeInTheDocument();
    // Not a switch: this catalogue lists, it does not operate.
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.getAllByText('להפעלה או כיבוי: מסך ההגדרות').length).toBeGreaterThan(0);
  });
});

// --- rules ------------------------------------------------------------------
describe('RulesPage', () => {
  it('lists the canonical smart rules', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<RulesPage />);

    expect(await screen.findByText('אור מטבח בערב')).toBeInTheDocument();
    expect(screen.getByText('מדליק את אור המטבח בשעה 18:00.')).toBeInTheDocument();
    expect(screen.getByText('מושבת')).toBeInTheDocument();
  });

  it('offers no edit control, because no bridge implements one', async () => {
    // Rewriting a rule is a compound change the contract cannot carry, so no
    // bridge implements it. A locked button repeated on every card was
    // furniture: it said the same nothing six times.
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<RulesPage />);

    await screen.findByText('אור מטבח בערב');
    expect(screen.queryByText('עריכה')).not.toBeInTheDocument();
  });

  it('has an empty state', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ ...ALL_ROUTES, '/api/bobi/rules': makeRules({ rules: [], count: 0 }) }),
    );
    renderWithProviders(<RulesPage />);

    expect(await screen.findByText('אין כרגע כללים חכמים')).toBeInTheDocument();
  });
});

// --- shabbat ----------------------------------------------------------------
describe('ShabbatPage', () => {
  it('shows the times and profiles', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<ShabbatPage />);

    expect(await screen.findByText('18:52')).toBeInTheDocument();
    expect(screen.getByText('19:51')).toBeInTheDocument();
    // Appears as both the card heading and the profile's own label.
    expect(screen.getAllByText('כיבוי לפני שבת').length).toBeGreaterThan(0);
  });

  // The week has a name, and the household plans around it. The card used to
  // print the parasha as its only heading and the two times as small print
  // beside it — and the times were timestamps, because the bridge forwarded a
  // `jewish_calendar` sensor straight through.
  it('names the week and the Hebrew date', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<ShabbatPage />);

    expect(await screen.findByText('פרשת ראה')).toBeInTheDocument();
    expect(screen.getByText(/אלול/)).toBeInTheDocument();
  });

  it('resolves device tokens to friendly labels', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<ShabbatPage />);

    await screen.findByText('18:52');
    // The label, never the raw token.
    expect(screen.getAllByText('אור מטבח').length).toBeGreaterThan(0);
    expect(screen.queryByText('kitchen_light')).not.toBeInTheDocument();
  });

  it('shows the pre-Shabbat offset the bridge nests inside upcoming', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<ShabbatPage />);

    await screen.findByText('18:52');
    expect(screen.getByText(/20 דקות לפני הכניסה/)).toBeInTheDocument();
  });

  it('keeps each temperature tied to its air conditioner', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<ShabbatPage />);

    await screen.findByText('18:52');
    const row = screen.getByText('מזגן סלון').closest('div');
    expect(within(row as HTMLElement).getByText('24°')).toBeInTheDocument();
  });

  it('shows a non-numeric temperature as the bridge sent it', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        ...ALL_ROUTES,
        '/api/bobi/shabbat': makeShabbat({
          ac_temperatures: [
            { id: 'ac_salon', label: 'מזגן סלון', temperature: null, text: 'auto' },
          ],
        }),
      }),
    );
    renderWithProviders(<ShabbatPage />);

    await screen.findByText('18:52');
    expect(screen.getByText('auto')).toBeInTheDocument();
  });

  it('shows the times and saves nothing by itself', async () => {
    // Without a management bridge the screen is the read-only one: profiles and
    // temperatures as cards, and no control that could write.
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<ShabbatPage />);

    await screen.findByText('18:52');
    expect(screen.getByText('פרופילים')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();

    // queryAll, not getAll: with the locked edit button gone there may be no
    // buttons at all on this screen, which is the point.
    for (const button of screen.queryAllByRole('button')) {
      expect(button.textContent ?? '').not.toMatch(/^שמירה$|תצוגה מקדימה/);
    }
  });
});

// --- users ------------------------------------------------------------------
describe('UsersPage', () => {
  it('renders profiles and a read-only permissions matrix', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<UsersPage />);

    // Appears in the profile card and again as a matrix column header.
    expect((await screen.findAllByText('ינון')).length).toBeGreaterThan(0);
    expect(screen.getByText('שליטה במכשירים')).toBeInTheDocument();

    // Static indicators, not checkboxes.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).queryByRole('button')).not.toBeInTheDocument();
  });

  it('never shows a phone number or a LID', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    const { container } = renderWithProviders(<UsersPage />);

    await screen.findAllByText('ינון');
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/\+\d{9,}/);
    expect(text).not.toMatch(/\d{10}/);
    expect(text).toContain('מחובר ל-WhatsApp');
  });
});

// --- tasks ------------------------------------------------------------------
describe('TasksPage', () => {
  it('separates open from completed tasks', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('לקבוע תור לרופא')).toBeInTheDocument();
    expect(screen.getByText('משימות פתוחות')).toBeInTheDocument();
    expect(screen.getByText('הושלמו')).toBeInTheDocument();
  });

  it('offers no way to complete or delete a task', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<TasksPage />);

    await screen.findByText('לקבוע תור לרופא');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    for (const button of screen.getAllByRole('button')) {
      expect(button.textContent ?? '').not.toMatch(/מחיקה|סמן|הוספה/);
    }
  });

  it('has an empty state', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ ...ALL_ROUTES, '/api/bobi/tasks': makeTasks({ tasks: [], count: 0 }) }),
    );
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText('אין משימות פתוחות 🎉')).toBeInTheDocument();
  });
});

// --- diagnostics ------------------------------------------------------------
describe('DiagnosticsPage', () => {
  it('groups issues and keeps entity ids collapsed', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DiagnosticsPage />);

    expect(await screen.findByText('מצלמת ליה אינה זמינה')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /שגיאות \(1\)/ })).toBeInTheDocument();
    expect(screen.getByText('לנתק ולחבר את שקע המצלמה.')).toBeInTheDocument();

    const summary = screen.getByText('פרטים טכניים');
    expect(summary.closest('details')?.open).toBeFalsy();
    expect(summary.closest('details')?.textContent).toContain('camera.demo_girls');
  });

  it('lists the checks the bridge ran', async () => {
    vi.stubGlobal('fetch', mockApi(ALL_ROUTES));
    renderWithProviders(<DiagnosticsPage />);

    expect(await screen.findByText('בדיקות שבוצעו')).toBeInTheDocument();
    expect(screen.getByText('WhatsApp')).toBeInTheDocument();

    // A numeric check is informational: shown as a figure, not a pass badge.
    expect(screen.getByText('מכשירים בקטלוג')).toBeInTheDocument();
    expect(screen.getByText('18')).toBeInTheDocument();
  });

  it('celebrates an empty issue list', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        ...ALL_ROUTES,
        '/api/bobi/diagnostics': makeDiagnostics({ issues: [], issue_count: 0, ok: true }),
      }),
    );
    renderWithProviders(<DiagnosticsPage />);

    expect(await screen.findByText('לא נמצאו תקלות 🎉')).toBeInTheDocument();
  });
});
