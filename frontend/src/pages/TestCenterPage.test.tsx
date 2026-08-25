import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TestCenterPage } from './TestCenterPage';
import { renderWithProviders } from '@/test/utils';
import type { ProbeResult } from '@/types/api';

const probeResult: ProbeResult = {
  original_text: 'כבה מזגן הורים ב-1:30 בלילה',
  normalized_text: 'כבה מזגן הורים ב 1:30 בלילה',
  family: 'schedule',
  domain: 'climate',
  action: 'turn_off',
  target: {
    id: 'parents_ac',
    name: 'מזגן הורים',
    room: 'חדר הורים',
    matched_alias: 'מזגן הורים',
    confidence: 0.87,
  },
  schedule: {
    kind: 'one_time',
    time: '01:30',
    date: '2026-08-26',
    days: [],
    description: 'מחר בשעה 01:30',
  },
  skill: 'local_schedule',
  safe: true,
  would_execute: false,
  warnings: ['הפעולה מתוזמנת לשעת לילה מאוחרת.'],
  steps: [
    { id: 'text', label: 'טקסט', status: 'ok', value: 'כבה מזגן הורים ב-1:30 בלילה', detail: null },
    { id: 'normalize', label: 'נרמול', status: 'ok', value: 'כבה מזגן הורים ב 1:30 בלילה', detail: null },
    { id: 'understand', label: 'הבנה', status: 'ok', value: 'תזמון', detail: 'לכבות' },
    { id: 'target', label: 'יעד', status: 'ok', value: 'מזגן הורים', detail: null },
    { id: 'time', label: 'זמן', status: 'ok', value: '01:30', detail: 'מחר בשעה 01:30' },
    { id: 'skill', label: 'Skill', status: 'ok', value: 'local_schedule', detail: null },
    { id: 'safety', label: 'בדיקת בטיחות', status: 'ok', value: 'בטוח', detail: 'לא בוצעה שום פעולה' },
  ],
  confidence: 0.93,
  duration_ms: 4,
};

function stubFetch(result: ProbeResult = probeResult) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input.toString();
    if (url.includes('/probe/history')) {
      return new Response(JSON.stringify({ entries: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (init?.method === 'POST') {
      return new Response(JSON.stringify(result), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({ entries: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('TestCenterPage', () => {
  it('renders the input and the safety promise up front', () => {
    stubFetch();
    renderWithProviders(<TestCenterPage />);

    expect(screen.getByLabelText('כתוב משהו שהיית שולח לבובי')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /בדוק בלי לבצע/ })).toBeInTheDocument();
    expect(screen.getByText('שום פעולה לא תתבצע בפועל')).toBeInTheDocument();
  });

  it('will not submit an empty request', () => {
    stubFetch();
    renderWithProviders(<TestCenterPage />);
    expect(screen.getByRole('button', { name: /בדוק בלי לבצע/ })).toBeDisabled();
  });

  it('renders the full pipeline and states plainly that nothing ran', async () => {
    const user = userEvent.setup();
    stubFetch();
    renderWithProviders(<TestCenterPage />);

    await user.type(
      screen.getByLabelText('כתוב משהו שהיית שולח לבובי'),
      'כבה מזגן הורים ב-1:30 בלילה',
    );
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    // The safety banner is the most important thing on the page.
    expect(await screen.findByText('✅ בדיקה בלבד')).toBeInTheDocument();
    expect(
      screen.getByText('לא בוצעה שום פעולה. אף מכשיר לא הופעל ואף תזמון לא נוצר.'),
    ).toBeInTheDocument();

    // Every pipeline stage is rendered, in order.
    for (const label of ['טקסט', 'נרמול', 'הבנה', 'יעד', 'זמן', 'Skill', 'בדיקת בטיחות']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }

    // The resolved detail the user cares about. Scoped to the pipeline, since
    // the collapsed raw-JSON block repeats these values.
    const pipeline = screen.getByText('בדיקת בטיחות').closest('ol') as HTMLElement;
    expect(within(pipeline).getByText('מזגן הורים')).toBeInTheDocument();
    expect(within(pipeline).getByText('01:30')).toBeInTheDocument();
    expect(within(pipeline).getByText('local_schedule')).toBeInTheDocument();

    // Warnings are surfaced, not buried.
    expect(screen.getByText('הפעולה מתוזמנת לשעת לילה מאוחרת.')).toBeInTheDocument();
  });

  it('sends the typed text to the probe endpoint', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch();
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'תדליק את אור המטבח');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    await screen.findByText('✅ בדיקה בלבד');
    const posted = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(posted?.[0]?.toString()).toContain('/api/bobi/probe');
    expect(posted?.[1]?.body).toBe(JSON.stringify({ text: 'תדליק את אור המטבח' }));
  });

  it('marks a sensitive request as needing approval', async () => {
    const user = userEvent.setup();
    stubFetch({ ...probeResult, safe: false });
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'תדליק את הדוד');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    expect(await screen.findByText('דורש אישור')).toBeInTheDocument();
    // Even an unsafe request never claims it would execute.
    expect(screen.getByText('✅ בדיקה בלבד')).toBeInTheDocument();
  });

  it('offers the raw result as copyable JSON', async () => {
    const user = userEvent.setup();
    stubFetch();
    renderWithProviders(<TestCenterPage />);

    await user.type(screen.getByLabelText('כתוב משהו שהיית שולח לבובי'), 'בדיקה');
    await user.click(screen.getByRole('button', { name: /בדוק בלי לבצע/ }));

    expect(await screen.findByText('תוצאה מלאה (JSON)')).toBeInTheDocument();
  });

  it('runs an example when one is clicked', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch();
    renderWithProviders(<TestCenterPage />);

    await user.click(screen.getByRole('button', { name: 'מה הטמפרטורה בסלון' }));

    await screen.findByText('✅ בדיקה בלבד');
    const posted = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(posted?.[1]?.body).toContain('מה הטמפרטורה בסלון');
  });
});
