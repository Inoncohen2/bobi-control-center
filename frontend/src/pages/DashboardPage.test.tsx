import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { DashboardPage } from './DashboardPage';
import { makeStatus } from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';

describe('DashboardPage', () => {
  it('renders health cards, stats, activity and warnings', async () => {
    vi.stubGlobal('fetch', mockApi({ '/api/bobi/status': makeStatus() }));
    renderWithProviders(<DashboardPage />);

    // Health.
    expect(await screen.findByText('WhatsApp')).toBeInTheDocument();
    expect(screen.getAllByText('מחובר').length).toBeGreaterThan(0);

    // Stats.
    expect(screen.getByText('אוטומציות פעילות')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();

    // Activity timeline.
    expect(screen.getByText('מה קורה עכשיו')).toBeInTheDocument();
    expect(screen.getByText('בובי שלח תזכורת לפגישה')).toBeInTheDocument();
    expect(screen.getByText('08:42')).toBeInTheDocument();

    // Warnings, phrased for a human.
    expect(screen.getByText('דורש תשומת לב')).toBeInTheDocument();
    expect(screen.getByText('מצלמת ליה אינה זמינה')).toBeInTheDocument();
  });

  it('keeps technical detail behind a disclosure', async () => {
    vi.stubGlobal('fetch', mockApi({ '/api/bobi/status': makeStatus() }));
    renderWithProviders(<DashboardPage />);

    await screen.findByText('מצלמת ליה אינה זמינה');

    const disclosure = screen.getAllByText('פרטים טכניים')[0];
    expect(disclosure).toBeInTheDocument();
    // The <details> wrapper is collapsed, so the identifier is not surfaced.
    expect(disclosure?.closest('details')?.open).toBeFalsy();
  });

  it('shows a friendly message and technical details when the request fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              code: 'upstream_unavailable',
              message: 'לא הצלחתי לטעון את מצב המערכת',
              details: {},
            }),
            { status: 502, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    );
    renderWithProviders(<DashboardPage />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('לא הצלחתי לטעון את מצב המערכת');
    // No HTTP status, exception name or traceback in what the user sees.
    expect(alert.textContent).not.toMatch(/Traceback|KeyError|HTTP 5/);
  });

  it('shows a celebratory empty state when nothing needs attention', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ '/api/bobi/status': makeStatus({ attention: [] }) }),
    );
    renderWithProviders(<DashboardPage />);

    await waitFor(() => expect(screen.getByText('הכול תקין 🎉')).toBeInTheDocument());
  });
});
