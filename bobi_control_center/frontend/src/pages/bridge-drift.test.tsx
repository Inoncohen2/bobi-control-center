import { expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { BridgeContractPage } from '@/pages/BridgeContractPage';
import { mockApi, renderWithProviders } from '@/test/utils';

const CONTRACT = {
  app_version: '3.22.0',
  implemented: ['bobi_cc_manage_contract'],
  missing: [],
  services: [],
  common_commit_inputs: [],
  common_commit_outputs: [],
  never_called_domains: [],
  never_requested: [],
  risk_to_role: {},
};

it('surfaces vocabulary drift from the live contract', async () => {
  vi.stubGlobal(
    'fetch',
    mockApi({
      '/api/bobi/manage/bridge-contract': CONTRACT,
      '/api/bobi/manage/bridge-drift': {
        ok: false,
        contract_available: true,
        contract_version: '3c',
        unknown_resources: [],
        unknown_operations: ['devices.super_mode'],
        missing_services: [],
        writes_enabled: true,
      },
    }),
  );

  renderWithProviders(<BridgeContractPage />);

  expect(await screen.findByText('נמצא drift בחוזה החי')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('devices.super_mode');
});

it('states that the live vocabulary matches when no drift exists', async () => {
  vi.stubGlobal(
    'fetch',
    mockApi({
      '/api/bobi/manage/bridge-contract': CONTRACT,
      '/api/bobi/manage/bridge-drift': {
        ok: true,
        contract_available: true,
        contract_version: '3c',
        unknown_resources: [],
        unknown_operations: [],
        missing_services: [],
        writes_enabled: true,
      },
    }),
  );

  renderWithProviders(<BridgeContractPage />);
  expect(await screen.findByText('אין drift בשמות/פעולות')).toBeInTheDocument();
});
