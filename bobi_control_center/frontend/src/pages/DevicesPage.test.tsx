import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DevicesPage } from './DevicesPage';
import { makeDevice } from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';

const deviceList = {
  devices: [
    makeDevice({ id: 'kitchen_light', display_name: 'אור מטבח', room: 'מטבח', category: 'light' }),
    makeDevice({
      id: 'living_room_ac',
      display_name: 'מזגן סלון',
      room: 'סלון',
      category: 'climate',
      aliases: ['מזגן סלון', 'המזגן בסלון'],
      advanced: {
        entity_id: 'climate.demo_living_room_ac',
        object_id: 'demo_living_room_ac',
        integration: 'demo',
        notes: [],
        raw: {},
      },
    }),
    makeDevice({
      id: 'lia_camera',
      display_name: 'מצלמת ליה',
      room: 'חדר בנות',
      category: 'camera',
      available: false,
      state: 'unavailable',
      state_label: 'לא זמין',
    }),
  ],
  rooms: ['סלון', 'מטבח', 'חדר בנות'],
  categories: ['camera', 'climate', 'light'],
};

function setup() {
  vi.stubGlobal('fetch', mockApi({ '/api/bobi/devices': deviceList }));
  return renderWithProviders(<DevicesPage />);
}

describe('DevicesPage', () => {
  it('groups devices by room', async () => {
    setup();
    expect(await screen.findByText('אור מטבח')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /סלון/ })).toBeInTheDocument();
    expect(screen.getByText('מזגן סלון')).toBeInTheDocument();
  });

  it('filters as the user types, including by alias', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('אור מטבח');

    await user.type(screen.getByLabelText('חיפוש מכשירים'), 'המזגן בסלון');

    await waitFor(() => expect(screen.queryByText('אור מטבח')).not.toBeInTheDocument());
    expect(screen.getByText('מזגן סלון')).toBeInTheDocument();
  });

  it('offers an empty state with a way out when nothing matches', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('אור מטבח');

    await user.type(screen.getByLabelText('חיפוש מכשירים'), 'קוקוריקו');

    expect(await screen.findByText('לא נמצאו מכשירים שמתאימים לסינון')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'ניקוי סינון' }));
    expect(await screen.findByText('אור מטבח')).toBeInTheDocument();
  });

  it('filters by room through the filter panel', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('אור מטבח');

    await user.click(screen.getByRole('button', { name: /סינון/ }));
    await user.click(screen.getByRole('button', { name: 'מטבח' }));

    await waitFor(() => expect(screen.queryByText('מזגן סלון')).not.toBeInTheDocument());
    expect(screen.getByText('אור מטבח')).toBeInTheDocument();
  });

  it('marks an unavailable device without relying on colour alone', async () => {
    setup();
    expect(await screen.findByText('מצלמת ליה')).toBeInTheDocument();
    expect(screen.getByText('לא זמין')).toBeInTheDocument();
  });

  it('keeps the entity id out of the card and behind the advanced panel', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('מזגן סלון');

    // Not on the card itself.
    expect(screen.queryByText(/climate\./)).not.toBeInTheDocument();

    await user.click(screen.getByText('מזגן סלון'));

    // In the detail view it lives inside a collapsed "מידע טכני" disclosure.
    const summary = await screen.findByText('מידע טכני');
    expect(summary.closest('details')?.open).toBeFalsy();
    expect(screen.getByText('climate.demo_living_room_ac')).toBeInTheDocument();
  });

  it('shows the aliases Bobi understands in the detail view', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('מזגן סלון');

    await user.click(screen.getByText('מזגן סלון'));

    expect(await screen.findByText('כינויים שבובי מבין')).toBeInTheDocument();
    expect(screen.getByText('המזגן בסלון')).toBeInTheDocument();
  });
});
