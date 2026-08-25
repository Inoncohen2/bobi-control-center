import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiUrl, resolveBasePath } from './client';

/** Point `window.location.pathname` at a value, the way Ingress would. */
function servedAt(pathname: string) {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { ...window.location, pathname },
  });
}

describe('resolveBasePath (Ingress-safe routing)', () => {
  it('returns an empty base at the domain root', () => {
    expect(resolveBasePath('/')).toBe('');
  });

  it('derives the generated Ingress prefix', () => {
    expect(resolveBasePath('/api/hassio_ingress/abc123XYZ/')).toBe(
      '/api/hassio_ingress/abc123XYZ',
    );
  });

  it('works whether or not the prefix has a trailing slash', () => {
    expect(resolveBasePath('/api/hassio_ingress/abc123')).toBe('/api/hassio_ingress/abc123');
    expect(resolveBasePath('/api/hassio_ingress/abc123/')).toBe('/api/hassio_ingress/abc123');
  });

  it('strips a trailing index.html', () => {
    expect(resolveBasePath('/api/hassio_ingress/abc123/index.html')).toBe(
      '/api/hassio_ingress/abc123',
    );
  });

  it('handles a plain sub-path deployment', () => {
    expect(resolveBasePath('/bobi/')).toBe('/bobi');
  });

  it('collapses repeated trailing slashes rather than emitting //api', () => {
    expect(resolveBasePath('///')).toBe('');
  });
});

describe('apiUrl', () => {
  afterEach(() => servedAt('/'));

  it('is relative to the app root at the domain root', () => {
    servedAt('/');
    expect(apiUrl('/api/bobi/status')).toBe('/api/bobi/status');
  });

  it('prefixes requests with the Ingress path', () => {
    servedAt('/api/hassio_ingress/tok3n/');
    expect(apiUrl('/api/bobi/status')).toBe('/api/hassio_ingress/tok3n/api/bobi/status');
  });

  it('never produces a double slash', () => {
    servedAt('/');
    expect(apiUrl('/api/bobi/status')).not.toContain('//');
  });

  it('never emits an absolute URL to another host', () => {
    servedAt('/api/hassio_ingress/tok3n/');
    const url = apiUrl('/api/bobi/devices');
    expect(url.startsWith('http://')).toBe(false);
    expect(url.startsWith('https://')).toBe(false);
    expect(url).not.toContain('supervisor');
    expect(url).not.toContain('homeassistant.local');
  });

  it('survives a hash route, because the hash is not part of the path', () => {
    servedAt('/api/hassio_ingress/tok3n/');
    // With a HashRouter, /#/devices leaves pathname untouched.
    expect(apiUrl('/api/bobi/devices')).toBe('/api/hassio_ingress/tok3n/api/bobi/devices');
  });
});

describe('ApiError', () => {
  it('recognises a disconnected bridge', () => {
    expect(new ApiError('x', 'upstream_unavailable', 502, {}).isDisconnected).toBe(true);
    expect(new ApiError('x', 'bridge_service_missing', 502, {}).isDisconnected).toBe(true);
    expect(new ApiError('x', 'ha_unauthorized', 502, {}).isDisconnected).toBe(true);
    expect(new ApiError('x', 'network_error', 0, {}).isDisconnected).toBe(true);
  });

  it('does not treat a validation error as a disconnection', () => {
    expect(new ApiError('x', 'validation_error', 422, {}).isDisconnected).toBe(false);
  });

  it('keeps technical detail separate from the user-facing message', () => {
    const error = new ApiError('לא הצלחתי', 'ha_error', 500, { service: 'script.bobi_cc_status' });
    expect(error.message).toBe('לא הצלחתי');
    expect(error.technical).toContain('code: ha_error');
    expect(error.technical).toContain('status: 500');
  });
});

describe('request URLs actually sent', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends every API call through the Ingress prefix', async () => {
    servedAt('/api/hassio_ingress/tok3n/');
    // Parameters are declared so `mock.calls` stays typed for the assertion.
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { fetchStatus } = await import('./bobi');
    await fetchStatus();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/hassio_ingress/tok3n/api/bobi/status',
    );
  });
});
