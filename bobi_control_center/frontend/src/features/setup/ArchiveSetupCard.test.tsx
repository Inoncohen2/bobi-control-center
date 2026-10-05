import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { setupApi, type ArchiveSetupSnapshot } from '@/api/setup';
import { ArchiveSetupCard } from './ArchiveSetupCard';

const endpoint = 'https://archive-dev.example/functions/v1/bobi-archive-next';
const secret = 'private-installation-token-aaaaaaaaaaaaaaaaaaaaaaaa';
const local: ArchiveSetupSnapshot = {
  mode: 'local', ready: true,
  cloud: { configured: false, ready: false, integration_key: '', endpoint: '', has_secret: false, reason: 'archive_provider_not_configured', checked_ts: 0, check_fresh: false },
};
const cloud: ArchiveSetupSnapshot = {
  mode: 'cloud', ready: true,
  cloud: { configured: true, ready: true, integration_key: 'archive', endpoint, has_secret: true, reason: 'archive_connection_ready', checked_ts: 1000, check_fresh: true },
};

function mount(initial = local, disabled = false) {
  const onSaved = vi.fn(async () => {});
  const onBusyChange = vi.fn();
  render(<ArchiveSetupCard initial={initial} disabled={disabled} onSaved={onSaved} onBusyChange={onBusyChange} />);
  return { onSaved, onBusyChange };
}

function mockCloud(check = cloud) {
  const save = vi.spyOn(setupApi, 'saveArchiveIntegration').mockResolvedValue({ integration_key: 'archive', integration_type: 'bobi_archive', display_name: 'Archive', enabled: true, endpoint, has_secret_ref: true });
  const probe = vi.spyOn(setupApi, 'checkArchive').mockResolvedValue(check);
  const select = vi.spyOn(setupApi, 'selectArchiveMode').mockResolvedValue(cloud);
  return { save, probe, select };
}

describe('archive setup', () => {
  it('defaults to local and choosing local needs no cloud request or secret', async () => {
    const user = userEvent.setup();
    const mocks = mockCloud();
    const { onSaved } = mount();
    expect(screen.getByRole('radio', { name: /מקומי/ })).toBeChecked();
    expect(screen.queryByLabelText('מפתח גישה לארכיון')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'בחר אחסון מקומי' }));
    expect(await screen.findByRole('status')).toHaveTextContent('קבצים חדשים יישמרו באחסון המקומי');
    expect(mocks.select).toHaveBeenCalledWith('local');
    expect(mocks.save).not.toHaveBeenCalled();
    expect(mocks.probe).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it('selects cloud only after saved encrypted credentials pass the handshake', async () => {
    const user = userEvent.setup();
    const mocks = mockCloud();
    const { onBusyChange } = mount();
    await user.click(screen.getByRole('radio', { name: /ענן/ }));
    await user.type(screen.getByLabelText('כתובת חיבור הארכיון'), endpoint);
    const password = screen.getByLabelText('מפתח גישה לארכיון');
    expect(password).toHaveAttribute('type', 'password');
    await user.type(password, secret);
    await user.click(screen.getByRole('button', { name: 'שמור, בדוק ובחר ענן' }));
    expect(await screen.findByRole('status')).toHaveTextContent('חיבור הענן נבדק ונבחר');
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ integration_type: 'bobi_archive', secret_value: secret, endpoint }));
    expect(mocks.save.mock.invocationCallOrder[0]).toBeLessThan(mocks.probe.mock.invocationCallOrder[0] ?? 0);
    expect(mocks.probe.mock.invocationCallOrder[0]).toBeLessThan(mocks.select.mock.invocationCallOrder[0] ?? 0);
    expect(mocks.select).toHaveBeenCalledWith('cloud');
    expect(password).toHaveValue('');
    expect(document.body.textContent).not.toContain(secret);
    expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
  });

  it.each(['archive_generic_protocol_required', 'archive_installation_mismatch'])('rejects an incompatible probe: %s', async (reason) => {
    const user = userEvent.setup();
    const mocks = mockCloud({ ...cloud, ready: false, cloud: { ...cloud.cloud, ready: false, reason } });
    const { onSaved } = mount(cloud);
    await user.click(screen.getByRole('button', { name: 'שמור, בדוק ובחר ענן' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(reason === 'archive_installation_mismatch' ? 'התקנה אחרת' : 'אינו תומך בארכיון');
    expect(mocks.select).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it('preserves an existing encrypted key when its input is empty', async () => {
    const user = userEvent.setup();
    const mocks = mockCloud();
    mount(cloud);
    expect(screen.getByLabelText('מפתח גישה לארכיון')).not.toBeRequired();
    await user.click(screen.getByRole('button', { name: 'שמור, בדוק ובחר ענן' }));
    await screen.findByRole('status');
    expect(mocks.save.mock.calls[0]?.[0].secret_value).toBeUndefined();
    expect(mocks.save.mock.calls[0]?.[0].integration_key).toBe('archive');
  });

  it('requires a new key for an endpoint change and clears it after a failed save', async () => {
    const user = userEvent.setup();
    const mocks = mockCloud();
    mocks.save.mockRejectedValue(new Error(secret));
    mount(cloud);
    const address = screen.getByLabelText('כתובת חיבור הארכיון');
    await user.clear(address);
    await user.type(address, 'https://other-dev.example/archive');
    const password = screen.getByLabelText('מפתח גישה לארכיון');
    expect(password).toBeRequired();
    await user.type(password, secret);
    await user.click(screen.getByRole('button', { name: 'שמור, בדוק ובחר ענן' }));
    await screen.findByRole('alert');
    expect(password).toHaveValue('');
    expect(document.body.textContent).not.toContain(secret);
    expect(mocks.probe).not.toHaveBeenCalled();
    expect(mocks.select).not.toHaveBeenCalled();
  });

  it('blocks another save while checking and disables the form during other wizard work', async () => {
    const user = userEvent.setup();
    const mocks = mockCloud();
    let resolve!: (value: ArchiveSetupSnapshot) => void;
    mocks.probe.mockImplementation(() => new Promise((done) => { resolve = done; }));
    mount(cloud);
    await user.click(screen.getByRole('button', { name: 'שמור, בדוק ובחר ענן' }));
    await waitFor(() => expect(mocks.probe).toHaveBeenCalledOnce());
    expect(screen.getByRole('button')).toBeDisabled();
    expect(screen.getByLabelText('כתובת חיבור הארכיון')).toBeDisabled();
    expect(mocks.select).not.toHaveBeenCalled();
    resolve(cloud);
    await screen.findByRole('status');
    expect(mocks.save).toHaveBeenCalledOnce();
  });

  it('disables archive controls while another wizard action runs', () => {
    mount(local, true);
    expect(screen.getByRole('button')).toBeDisabled();
    expect(screen.getByRole('radio', { name: /ענן/ })).toBeDisabled();
  });
});
