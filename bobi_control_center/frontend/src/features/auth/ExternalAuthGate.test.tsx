import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ExternalAuthGate } from './ExternalAuthGate';

afterEach(() => {
  vi.restoreAllMocks();
});

it('passes through Home Assistant Ingress without another login', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ authenticated: true, mode: 'home_assistant' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

  render(
    <ExternalAuthGate>
      <div>המערכת</div>
    </ExternalAuthGate>,
  );

  expect(await screen.findByText('המערכת')).toBeInTheDocument();
  expect(screen.queryByLabelText('סיסמה')).not.toBeInTheDocument();
});

it('requires and submits the external password', async () => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ code: 'authentication_required', message: 'נדרשת התחברות לבובי' }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ authenticated: true, mode: 'external' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

  render(
    <ExternalAuthGate>
      <div>המערכת</div>
    </ExternalAuthGate>,
  );

  const password = await screen.findByLabelText('סיסמה');
  await userEvent.type(password, 'correct horse battery staple');
  await userEvent.click(screen.getByRole('button', { name: 'כניסה מאובטחת' }));

  expect(await screen.findByText('המערכת')).toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(fetch.mock.calls[1]?.[1]?.body).toBe(
    JSON.stringify({ password: 'correct horse battery staple' }),
  );
});
