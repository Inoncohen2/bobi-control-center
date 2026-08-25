import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AutomationsPage } from './AutomationsPage';
import { makeAutomation } from '@/test/fixtures';
import { renderWithProviders } from '@/test/utils';

const automations = {
  automations: [
    makeAutomation(),
    makeAutomation({
      id: 'living_room_ac_night',
      name: 'מזגן סלון בלילה',
      automation_type: 'time_window',
      start_time: '22:00',
      end_time: '01:00',
      crosses_midnight: true,
      summary: 'בכל יום בין 22:00 ל-01:00 (למחרת) להדליק את מזגן סלון',
    }),
    makeAutomation({
      id: 'vacuum_weekly',
      name: 'רובי בימי שני',
      enabled: false,
      automation_type: 'weekly',
      start_time: '10:00',
      end_time: null,
      summary: 'בכל יום שני בשעה 10:00 להפעיל את רובי',
    }),
  ],
};

const deletePreview = {
  summary: 'למחוק את „רובי בימי שני”?',
  lines: [{ text: 'בכל יום שני בשעה 10:00 להפעיל את רובי', emphasis: false }],
  warnings: ['האוטומציה תפסיק לרוץ לגמרי.'],
  requires_confirmation: true,
  destructive: true,
  token: 'preview-token-abc',
};

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input.toString();
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });

    if (url.includes('/delete/preview')) return json(deletePreview);
    if (url.includes('/delete/confirm')) {
      return json({ success: true, message: 'נמחק', dry_run: true, applied: false, audit_id: 'a1' });
    }
    if (init?.method === 'POST') return json(makeAutomation());
    if (url.includes('/api/bobi/automations')) return json(automations);
    return json({ devices: [], rooms: [], categories: [] });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('AutomationsPage', () => {
  it('shows the server-built summary for each automation', async () => {
    stubFetch();
    renderWithProviders(<AutomationsPage />);

    expect(await screen.findByText('אור מטבח בערב')).toBeInTheDocument();
    expect(
      screen.getByText('בימים ראשון עד חמישי בין 18:00 ל-22:00 להדליק את אור מטבח'),
    ).toBeInTheDocument();
  });

  it('flags a cross-midnight window and only that one', async () => {
    stubFetch();
    renderWithProviders(<AutomationsPage />);
    await screen.findByText('מזגן סלון בלילה');

    // Exactly one automation crosses midnight in this fixture.
    const badges = screen.getAllByText('+ יום הבא');
    expect(badges).toHaveLength(1);

    const card = badges[0]?.closest('li');
    expect(within(card as HTMLElement).getByText('מזגן סלון בלילה')).toBeInTheDocument();
  });

  it('renders the time window in an isolated LTR run so the arrow reads correctly', async () => {
    stubFetch();
    renderWithProviders(<AutomationsPage />);
    await screen.findByText('מזגן סלון בלילה');

    const window = screen.getByText(/22:00 → 01:00/);
    expect(window).toHaveAttribute('dir', 'ltr');
  });

  it('distinguishes enabled from disabled', async () => {
    stubFetch();
    renderWithProviders(<AutomationsPage />);
    await screen.findByText('רובי בימי שני');

    expect(screen.getByText('מושבת')).toBeInTheDocument();
    expect(screen.getAllByText('פעיל')).toHaveLength(2);
  });

  it('requires a preview and an explicit confirmation before deleting', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch();
    renderWithProviders(<AutomationsPage />);
    await screen.findByText('רובי בימי שני');

    await user.click(screen.getByRole('button', { name: 'מחיקת רובי בימי שני' }));

    // The preview arrives from the server and is shown before anything happens.
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('למחוק את „רובי בימי שני”?');
    expect(dialog).toHaveTextContent('האוטומציה תפסיק לרוץ לגמרי.');
    expect(dialog).toHaveTextContent('זו תצוגה מקדימה. שום דבר לא נשמר עד שתאשרו.');

    // Nothing was deleted yet.
    expect(
      fetchMock.mock.calls.some(([url]) => url.toString().includes('/delete/confirm')),
    ).toBe(false);

    await user.click(within(dialog).getByRole('button', { name: 'מחיקה' }));

    // Only now, and carrying the token issued with the preview.
    const confirmCall = fetchMock.mock.calls.find(([url]) =>
      url.toString().includes('/delete/confirm'),
    );
    expect(confirmCall).toBeDefined();
    expect(confirmCall?.[1]?.body).toBe(JSON.stringify({ token: 'preview-token-abc' }));
  });

  it('cancelling the confirmation deletes nothing', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch();
    renderWithProviders(<AutomationsPage />);
    await screen.findByText('רובי בימי שני');

    await user.click(screen.getByRole('button', { name: 'מחיקת רובי בימי שני' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'ביטול' }));

    expect(
      fetchMock.mock.calls.some(([url]) => url.toString().includes('/delete/confirm')),
    ).toBe(false);
  });

  it('keeps the internal object id behind the advanced disclosure', async () => {
    stubFetch();
    renderWithProviders(<AutomationsPage />);
    await screen.findByText('אור מטבח בערב');

    const disclosures = screen.getAllByText('מתקדם');
    expect(disclosures.length).toBeGreaterThan(0);
    expect(disclosures[0]?.closest('details')?.open).toBeFalsy();
  });
});
