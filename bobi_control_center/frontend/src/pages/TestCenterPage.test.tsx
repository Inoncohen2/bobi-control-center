import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TestCenterPage } from './TestCenterPage';
import { makeProbe } from '@/test/fixtures';
import { renderWithProviders } from '@/test/utils';
import type { BridgeProbe } from '@/types/api';

function stubProbe(result: BridgeProbe = makeProbe()) {
  // Parameters are declared so `mock.calls` stays typed for the assertions.
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(result), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('TestCenterPage', () => {
  it('states the safety promise before anything is submitted', () => {
    stubProbe();
    renderWithProviders(<TestCenterPage />);

    expect(screen.getByLabelText('כתוב משהו שהיית שולח לבובי')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /בדוק בלי לבצע/ })).toBeInTheDocument();
    expect(screen.getByText('שום פעולה לא תתבצע בפועל')).toBeInTheDocument();
  });

  it('will not submit an empty request', () => {
    stubProbe();
    renderWithProviders(<TestCenterPage />);
    expect(screen.getByRole('button', { name: /בדוק בלי לבצע/ })).toBeDisabled();
  });

  it('displays the required probe-only banner prominently', async () => {
    const user = userEvent.setup();
    stubProbe();
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'כבה מזגן הורים');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    expect(await screen.findByText('בדיקה בלבד — לא בוצעה שום פעולה')).toBeInTheDocument();
  });

  it('builds the pipeline from the bridge fields', async () => {
    const user = userEvent.setup();
    stubProbe();
    renderWithProviders(<TestCenterPage />);

    await user.type(
      screen.getByLabelText('כתוב משהו שהיית שולח לבובי'),
      'כבה מזגן הורים ב-1:30 בלילה',
    );
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    await screen.findByText('בדיקה בלבד — לא בוצעה שום פעולה');

    const pipeline = screen.getByText('בדיקת בטיחות').closest('ol') as HTMLElement;
    for (const label of ['טקסט', 'הבנה', 'יעד', 'תזמון', 'Skill', 'בדיקת בטיחות']) {
      expect(within(pipeline).getByText(label)).toBeInTheDocument();
    }
    expect(within(pipeline).getByText('מזגן הורים')).toBeInTheDocument();
    expect(within(pipeline).getByText('local_schedule')).toBeInTheDocument();
    expect(within(pipeline).getByText('לא בוצעה שום פעולה')).toBeInTheDocument();
  });

  it('shows what Bobi understood', async () => {
    const user = userEvent.setup();
    stubProbe();
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'כבה מזגן הורים');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    const heading = await screen.findByText('מה בובי הבין');
    // Scoped to the table: the pipeline shows the same values above it.
    const table = heading.closest('div') as HTMLElement;
    expect(within(table).getByText('כוונה')).toBeInTheDocument();
    expect(within(table).getByText('device_control')).toBeInTheDocument();
  });

  it('reports a request the bridge did not understand', async () => {
    const user = userEvent.setup();
    stubProbe(
      makeProbe({
        handled: false,
        status: 'not_understood',
        terminal: false,
        skill: null,
        understanding: null,
        schedule_valid: null,
        schedule_reason: 'לא זוהתה כוונה בטקסט',
        schedule_kind: null,
      }),
    );
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'קשקוש');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    // Rendered both as a badge and as a pipeline stage value.
    expect((await screen.findAllByText('לא הובן')).length).toBeGreaterThan(0);
    // Even an unhandled request still says nothing was executed.
    expect(screen.getByText('בדיקה בלבד — לא בוצעה שום פעולה')).toBeInTheDocument();
  });

  it('surfaces an invalid schedule as a failed pipeline stage', async () => {
    const user = userEvent.setup();
    stubProbe(
      makeProbe({
        schedule_valid: false,
        schedule_reason: 'שעה לא תקינה',
        schedule_kind: null,
      }),
    );
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'כבה ב-99:99');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    expect(await screen.findByText('תזמון לא תקין')).toBeInTheDocument();
    expect(screen.getAllByText('שעה לא תקינה').length).toBeGreaterThan(0);
  });

  it('posts the typed text to the probe endpoint', async () => {
    const user = userEvent.setup();
    const fetchMock = stubProbe();
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'תדליק את אור המטבח');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    await screen.findByText('בדיקה בלבד — לא בוצעה שום פעולה');
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain('/api/bobi/probe');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBe(JSON.stringify({ text: 'תדליק את אור המטבח' }));
  });

  it('offers no execute control of any kind', async () => {
    const user = userEvent.setup();
    stubProbe();
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'כבה מזגן הורים');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));
    await screen.findByText('בדיקה בלבד — לא בוצעה שום פעולה');

    // The probe button is the only submit control, and it says so.
    const submitButtons = screen
      .getAllByRole('button')
      .map((button) => button.textContent ?? '')
      .filter((name) => /בצע|הפעל|שלח/.test(name));
    expect(submitButtons).toEqual(['בדוק בלי לבצע']);
  });

  it('reports a bridge failure without a traceback', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              code: 'bridge_service_missing',
              message: 'שירות הגשר script.bobi_cc_probe לא נמצא ב-Home Assistant',
              details: {},
            }),
            { status: 502, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    );
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'בדיקה');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('לא הצלחתי לקבל נתונים מ-Home Assistant');
    expect(alert.textContent).not.toMatch(/Traceback|KeyError/);
  });
});
