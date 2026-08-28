/*
 * A deliberately small service worker.
 *
 * Its whole job is to make the installed app open instantly and say something
 * sensible with no signal. It is **not** an offline copy of the house: every
 * `/api` request goes to the network and is never cached, because a cached
 * reading is a lie about a light that may since have been switched off, and a
 * cached write is unthinkable.
 *
 * So: the shell — the HTML, the JavaScript, the icons — is cached and served
 * cache-first, and everything else is network-only.
 */

const SHELL = 'bobi-shell-v1';

/** Resolved against the worker's own URL, so an Ingress prefix is inherited. */
const SHELL_FILES = ['./', './index.html', './manifest.webmanifest', './icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((cache) => cache.addAll(SHELL_FILES))
      // A shell file that 404s must not wedge the install: the app still works
      // online, and refusing to activate would leave the old worker in place.
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name !== SHELL).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // The house's live state, and every write. Never cached, never replayed.
  if (url.pathname.includes('/api/')) return;

  // A navigation is answered from the network when there is one and from the
  // cached shell when there is not, so opening the app on a dead lift still
  // shows the app rather than the browser's error page.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match('./index.html', { ignoreSearch: true }).then(
          (hit) =>
            hit ??
            new Response('<!doctype html><meta charset="utf-8"><p dir="rtl">אין חיבור כרגע.</p>', {
              headers: { 'Content-Type': 'text/html; charset=utf-8' },
              status: 503,
            }),
        ),
      ),
    );
    return;
  }

  // Hashed build assets: the name changes when the content does, so a hit is
  // always current and a miss is filled once.
  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ??
        fetch(request).then((response) => {
          if (response.ok && response.type === 'basic') {
            const copy = response.clone();
            void caches.open(SHELL).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});
