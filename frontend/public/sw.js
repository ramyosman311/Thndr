/**
 * MIZAN service worker (Phase 21).
 *
 * Deliberately minimal: static/app-shell assets get a small runtime
 * cache for install-ability and offline shell rendering. Financial data
 * is never served from here.
 *
 * Hard rule: anything under /api/ is NEVER read from or written to Cache
 * Storage. The app's own fetch layer (lib/api.ts) already sets
 * `cache: "no-store"` on every API call to bypass the HTTP cache; this
 * worker must not reintroduce staleness at the Cache Storage layer below
 * that. Non-GET requests are never intercepted either.
 */

const CACHE_VERSION = "v1";
const CACHE_NAME = `mizan-static-${CACHE_VERSION}`;

self.addEventListener("install", () => {
  // No mandatory precache list -- the runtime cache below fills in
  // lazily as static assets are actually requested, so there is no
  // build-time asset manifest to keep in sync (and no way for a stale
  // list to break an install).
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
});

// Manual update flow: the page controls when a waiting worker takes over
// (see components/service-worker-registration.tsx) so an update never
// interrupts an in-progress transaction entry.
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isImmutableStaticAsset(url) {
  // Next.js build output under /_next/static/ is content-hashed --
  // identical bytes forever at a given URL, safe to cache-first.
  return url.pathname.startsWith("/_next/static/");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isApiRequest(url)) return;

  if (isImmutableStaticAsset(url)) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      })
    );
    return;
  }

  // Everything else same-origin (app shell HTML, manifest, icons, fonts):
  // network-first so the network is always authoritative when reachable,
  // falling back to the last cached copy only when offline.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
