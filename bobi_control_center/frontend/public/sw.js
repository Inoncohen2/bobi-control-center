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

/**
 * Bump this whenever a shell file's *content* can differ from what an
 * installed phone already cached.
 *
 * v1 → v2 because it had not been bumped when 3.12.1 rewrote the manifest, and
 * `activate` only deletes caches whose key differs from this one. The corrected
 * manifest was therefore never fetched by any device that already had the
 * worker: the old one was served from `bobi-shell-v1` for good, iOS kept
 * reading the `scope` that 3.12.1 removed, and deleting the home-screen icon
 * and adding it again re-installed the same stale manifest.
 */
const SHELL = 'bobi-shell-v2';

/** Resolved against the worker's own URL, so an Ingress prefix is inherited. */
const SHELL_FILES = ['./', './index.html', './manifest.webmanifest', './icon-192.png'];

/**
 * Shell files whose content changes without their name changing.
 *
 * The cache-first rule below is sound for `assets/index-<hash>.js`, where a
 * changed file is a changed URL and a hit is current by construction. These
 * three have fixed names, so cache-first pins whichever copy the worker
 * happened to fetch on the day it installed — which is the whole of the bug
 * above. They go to the network first and fall back to the cache, so the app
 * still opens with no signal.
 *
 * The manifest matters most: it is the file that decides whether iOS treats
 * this as an installed app at all.
 */
const ALWAYS_REVALIDATE = ['/manifest.webmanifest', '/index.html', '/icon-192.png'];

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

  const store = (response) => {
    if (response.ok && response.type === 'basic') {
      const copy = response.clone();
      void caches.open(SHELL).then((cache) => cache.put(request, copy));
    }
    return response;
  };

  // A fixed-name shell file. Ask the network, keep the answer, and fall back
  // to the cache only when there is no network — never the other way round, or
  // a corrected manifest can never reach a phone that cached the old one.
  if (ALWAYS_REVALIDATE.some((name) => url.pathname.endsWith(name))) {
    event.respondWith(
      fetch(request)
        .then(store)
        .catch(() =>
          caches
            .match(request, { ignoreSearch: true })
            .then((hit) => hit ?? Response.error()),
        ),
    );
    return;
  }

  // Hashed build assets: the name changes when the content does, so a hit is
  // always current and a miss is filled once.
  event.respondWith(caches.match(request).then((hit) => hit ?? fetch(request).then(store)));
});
