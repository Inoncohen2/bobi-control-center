/**
 * The bridge specification screen.
 *
 * It exists so that whoever writes the Home Assistant side can see what this
 * build sends without reading the build. Two properties matter: it names the
 * missing scripts precisely, and it carries nothing about the house.
 */

import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { BridgeContractPage } from '@/pages/BridgeContractPage';
import { mockApi, renderWithProviders } from '@/test/utils';

const CONTRACT = {
  app_version: '3.3.0',
  implemented: ['bobi_cc_manage_contract', 'bobi_cc_settings_snapshot'],
  missing: ['bobi_cc_scenes_snapshot', 'bobi_cc_scene_commit'],
  services: [
    {
      name: 'bobi_cc_settings_snapshot',
      kind: 'read',
      purpose: 'Current state of settings.',
      resource: 'settings',
      operations: [],
      inputs: [],
      outputs: '{ "items": [] }',
      validation: ['Never include a Home Assistant entity_id.'],
      verification: 'Not applicable — read-only.',
      risk: 'read_only',
      operation_risk: {},
    },
    {
      name: 'bobi_cc_scene_commit',
      kind: 'write',
      purpose: 'Activate one scene.',
      resource: 'scenes',
      operations: ['activate', 'rename'],
      inputs: [
        { name: 'preview_token', type: 'string, non-empty', note: 'Refuse without it.' },
      ],
      outputs: '{ "executed": true }',
      validation: ['Refuse a commit with an empty preview_token.'],
      verification: 'Read the value back after writing it.',
      risk: 'low',
      operation_risk: { activate: 'low', rename: 'low' },
    },
  ],
  common_commit_inputs: [
    { name: 'preview_token', type: 'string, non-empty', note: 'Single-use.' },
  ],
  common_commit_outputs: [{ name: 'executed', type: 'boolean', note: 'Applied?' }],
  never_called_domains: ['light', 'todo', 'homeassistant'],
  never_requested: ['Restarting Home Assistant'],
  risk_to_role: { low: 'operator', destructive: 'owner' },
};

function stub(body: unknown = CONTRACT) {
  const fetchMock = mockApi({ '/api/bobi/manage/bridge-contract': body });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('the bridge specification screen', () => {
  it('counts what exists and what does not', async () => {
    stub();
    renderWithProviders(<BridgeContractPage />);

    expect(await screen.findByText(/2 קיימים/)).toBeInTheDocument();
    expect(screen.getByText(/2 חסרים/)).toBeInTheDocument();
  });

  it('shows the missing ones first, and nothing else', async () => {
    stub();
    renderWithProviders(<BridgeContractPage />);

    expect(await screen.findByText('script.bobi_cc_scene_commit')).toBeInTheDocument();
    // The implemented one is filtered out until "all" is chosen.
    expect(screen.queryByText('script.bobi_cc_settings_snapshot')).not.toBeInTheDocument();
  });

  it('shows every service when asked', async () => {
    stub();
    renderWithProviders(<BridgeContractPage />);

    await userEvent.click(await screen.findByRole('button', { name: /כל 2 השירותים/ }));

    expect(screen.getByText('script.bobi_cc_settings_snapshot')).toBeInTheDocument();
    expect(screen.getByText('script.bobi_cc_scene_commit')).toBeInTheDocument();
  });

  it('states the token requirement and the verification for a write bridge', async () => {
    stub();
    renderWithProviders(<BridgeContractPage />);

    expect(await screen.findByText(/Refuse a commit with an empty preview_token/)).toBeInTheDocument();
    expect(screen.getByText(/Read the value back after writing it/)).toBeInTheDocument();
  });

  it('rates each operation, so both sides agree on what a change costs', async () => {
    stub();
    renderWithProviders(<BridgeContractPage />);

    expect(await screen.findByText('activate · low')).toBeInTheDocument();
  });

  it('lists the domains that are never called', async () => {
    stub();
    renderWithProviders(<BridgeContractPage />);

    expect(await screen.findByText('light.*')).toBeInTheDocument();
    expect(screen.getByText('homeassistant.*')).toBeInTheDocument();
    expect(screen.getByText(/Restarting Home Assistant/)).toBeInTheDocument();
  });

  it('says so plainly when nothing is missing', async () => {
    stub({ ...CONTRACT, missing: [] });
    renderWithProviders(<BridgeContractPage />);

    expect(await screen.findByText(/כל הגשרים .* קיימים/)).toBeInTheDocument();
  });
});
