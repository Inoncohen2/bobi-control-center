import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';

import { setupApi, type SetupSnapshot } from '@/api/setup';
import { renderWithProviders } from '@/test/utils';
import { NextSetupPage } from './NextSetupPage';

it('keeps completion disabled after home discovery until the selected archive is verified', async () => {
  const user = userEvent.setup();
  const snapshot: SetupSnapshot = {
    installation_id: 'installation',
    setup: { completed: false, ready: false, missing_steps: ['archive_connection_check'] },
    messaging_configured: true, providers: [], users: [], linked_identities: 1,
    ai: { configured: true, active_provider: 'ai', providers: [] },
    archive: {
      mode: 'cloud', ready: false,
      cloud: { configured: true, ready: false, integration_key: 'archive', endpoint: 'https://archive-dev.example/archive', has_secret: true, reason: 'archive_connection_not_checked', checked_ts: 0, check_fresh: false },
    },
  };
  vi.spyOn(setupApi, 'status').mockResolvedValue(snapshot);
  vi.spyOn(setupApi, 'homeScan').mockResolvedValue({ ok: true, devices: 2, available_devices: 2, entities: 4, areas: 1, capabilities: 3, domains: [] });
  const complete = vi.spyOn(setupApi, 'complete');
  renderWithProviders(<NextSetupPage />);
  await screen.findByText('6. ארכיון מסמכים');
  await user.click(screen.getByRole('button', { name: 'סרוק את הבית' }));
  await screen.findByText('עדיין חסר: בדיקת חיבור לארכיון המסמכים');
  expect(screen.getByRole('button', { name: 'סיים הגדרה' })).toBeDisabled();
  expect(complete).not.toHaveBeenCalled();
});
