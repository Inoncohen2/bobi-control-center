import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter } from 'react-router-dom';

import { App } from './App';
import { ExternalAuthGate } from './features/auth/ExternalAuthGate';
import './index.css';
import { resolveBasePath } from '@/api/client';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Every fetch is a Home Assistant service call, so the defaults are
      // deliberately quiet: no refetch storm on focus, and a stale window that
      // lets screens without their own polling serve from cache.
      refetchOnWindowFocus: false,
      staleTime: 60_000,
      retry: 1,
    },
  },
});

const container = document.getElementById('root');
if (!container) {
  throw new Error('Missing #root element');
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ExternalAuthGate>
        <HashRouter>
          <App />
        </HashRouter>
      </ExternalAuthGate>
    </QueryClientProvider>
  </StrictMode>,
);

/**
 * Register the service worker, at whatever path this app was served from.
 *
 * `resolveBasePath` is the same function the API client uses to find its own
 * origin under a Home Assistant Ingress prefix, so the worker's scope matches
 * the app's rather than being hard-coded to `/` — which is a path this add-on
 * is never served from and could not claim if it were.
 *
 * Failure is silent on purpose. A service worker is a nicety: the app is fully
 * usable without one, and a browser that refuses to register it (private mode,
 * an insecure origin, a corporate policy) should get the app, not an error.
 */
if ('serviceWorker' in navigator) {
  // `resolveBasePath` returns the prefix without a trailing slash, and "" at
  // the root — so the slash is added here rather than assumed. Without it the
  // worker would be fetched from ".../hassio_ingress/<token>sw.js".
  const scope = `${resolveBasePath(window.location.pathname)}/`;
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register(`${scope}sw.js`, { scope }).catch(() => undefined);
  });
}
