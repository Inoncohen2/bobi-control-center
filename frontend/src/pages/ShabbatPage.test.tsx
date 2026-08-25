import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ShabbatPage } from './ShabbatPage';
import { makeShabbatConfig } from '@/test/fixtures';
import { renderWithProviders } from '@/test/utils';

const preview = {
  summary: '2 מכשירים · 2 טווחי שעות · 1 ממשיכים אחרי חצות',
  lines: [
    { text: 'מזגן סלון (סלון)', emphasis: true },
    { text: '  שישי: ⁦22:00 → 01:00⁩ + יום הבא · 3 שעות', emphasis: false },
  ],
  warnings: ['מזגן סלון: הטווח 22:00–01:00 ממשיך אל היום הבא.'],
  requires_confirmation: true,
  destructive: false,
  token: 'shabbat-token-xyz',
};

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input.toString();
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });

    if (url.includes('/shabbat/preview')) return json(preview);
    if (url.includes('/shabbat/confirm')) {
      return json({
        success: true,
        message: 'תזמוני השבת נשמרו',
        dry_run: true,
        applied: false,
        audit_id: 'a1',
      });
    }
    if (init?.method === 'POST') return json({});
    return json(makeShabbatConfig());
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('ShabbatPage', () => {
  it('shows the Shabbat times', async () => {
    stubFetch();
    renderWithProviders(<ShabbatPage />);

    expect(await screen.findByText('פרשת ראה')).toBeInTheDocument();
    expect(screen.getByText('18:52')).toBeInTheDocument();
    expect(screen.getByText('19:51')).toBeInTheDocument();
  });

  it('marks only the range that crosses midnight', async () => {
    stubFetch();
    renderWithProviders(<ShabbatPage />);
    await screen.findByText('מזגן סלון');

    const badges = screen.getAllByText('+ יום הבא');
    expect(badges).toHaveLength(1);

    // It belongs to the 22:00 → 01:00 range, not the 17:42 → 23:30 one.
    const row = badges[0]?.closest('li');
    expect(within(row as HTMLElement).getByText(/22:00 → 01:00/)).toBeInTheDocument();
  });

  it('recomputes the indicator as the user edits an end time', async () => {
    const user = userEvent.setup();
    stubFetch();
    renderWithProviders(<ShabbatPage />);
    await screen.findByText('אור מטבח');

    // The kitchen light starts as a same-day window.
    expect(screen.getAllByText('+ יום הבא')).toHaveLength(1);

    const kitchenCard = screen.getByText('אור מטבח').closest('li') as HTMLElement;
    const endInput = within(kitchenCard).getByLabelText('כיבוי');
    await user.clear(endInput);
    await user.type(endInput, '01:00');

    await waitFor(() => expect(screen.getAllByText('+ יום הבא')).toHaveLength(2));
  });

  it('never saves straight from the edit screen — preview then confirm', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch();
    renderWithProviders(<ShabbatPage />);
    await screen.findByText('אור מטבח');

    // Editing surfaces a save bar rather than saving.
    const kitchenCard = screen.getByText('אור מטבח').closest('li') as HTMLElement;
    await user.click(within(kitchenCard).getByRole('button', { name: 'טווח בשבת' }));

    expect(await screen.findByText('יש שינויים שלא נשמרו')).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) => url.toString().includes('/shabbat/confirm')),
    ).toBe(false);

    await user.click(screen.getByRole('button', { name: /תצוגה מקדימה/ }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('2 מכשירים');
    expect(dialog).toHaveTextContent('ממשיך אל היום הבא');
    // Still nothing saved.
    expect(
      fetchMock.mock.calls.some(([url]) => url.toString().includes('/shabbat/confirm')),
    ).toBe(false);

    await user.click(within(dialog).getByRole('button', { name: 'שמירה' }));

    const confirmCall = fetchMock.mock.calls.find(([url]) =>
      url.toString().includes('/shabbat/confirm'),
    );
    expect(confirmCall).toBeDefined();
    expect(confirmCall?.[1]?.body).toContain('shabbat-token-xyz');
  });

  it('reset discards unsaved edits', async () => {
    const user = userEvent.setup();
    stubFetch();
    renderWithProviders(<ShabbatPage />);
    await screen.findByText('אור מטבח');

    const kitchenCard = screen.getByText('אור מטבח').closest('li') as HTMLElement;
    await user.click(within(kitchenCard).getByRole('button', { name: 'טווח בשבת' }));
    await screen.findByText('יש שינויים שלא נשמרו');

    await user.click(screen.getByRole('button', { name: /איפוס/ }));

    await waitFor(() =>
      expect(screen.queryByText('יש שינויים שלא נשמרו')).not.toBeInTheDocument(),
    );
  });

  it('a disabled device is excluded rather than hidden', async () => {
    const user = userEvent.setup();
    stubFetch();
    renderWithProviders(<ShabbatPage />);
    await screen.findByText('אור מטבח');

    await user.click(screen.getByRole('switch', { name: 'הפעלת תזמון שבת עבור אור מטבח' }));

    expect(await screen.findByText('המכשיר לא ייכלל בשבת הקרובה.')).toBeInTheDocument();
  });
});
