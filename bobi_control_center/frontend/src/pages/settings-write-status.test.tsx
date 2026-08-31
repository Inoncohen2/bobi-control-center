import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SettingsPage } from './SettingsPage';
import {
  makeConnection,
  makeManagementWith,
  makeResourceSnapshot,
  makeStatus,
} from '@/test/fixtures';
import { mockApi, renderWithProviders } from '@/test/utils';

describe('SettingsPage write status', () => {
  it('separates blocked direct writes from the live Bobi bridge switch', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        '/api/bobi/connection': makeConnection({ unrestricted_writes: false }),
        '/api/bobi/status': makeStatus(),
        '/api/bobi/manage/contract': makeManagementWith('settings', {
          available: true,
          writes_enabled: true,
        }),
        '/api/bobi/manage/audit': { count: 0, records: [] },
        '/api/bobi/manage/settings/snapshot': makeResourceSnapshot(),
      }),
    );

    renderWithProviders(<SettingsPage />);

    const directLabel = await screen.findByText('כתיבה ישירה');
    const directRow = directLabel.closest('.border-b');
    expect(directRow).not.toBeNull();
    expect(within(directRow as HTMLElement).getByText('חסומה (כנדרש)')).toBeInTheDocument();

    const bridgeLabel = await screen.findByText('כתיבה דרך גשר בובי');
    const bridgeRow = bridgeLabel.closest('.border-b');
    expect(bridgeRow).not.toBeNull();
    expect(within(bridgeRow as HTMLElement).getByText('מאופשרת')).toBeInTheDocument();

    expect(screen.queryByText('בשלב זה היישום קורא נתונים בלבד ואינו משנה דבר.')).not.toBeInTheDocument();
  });
});
