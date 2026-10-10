// Minimal service worker: caches the app shell so Driftway is installable and
// opens fast. Network-first for navigation, cache fallback when offline.
// v2 (0.8): only Driftway's own files are cached. v1 also kept every map
// image and font from other sites, in a cache that never shrank; renaming the
// cache makes "activate" below delete it.
const CACHE = "driftway-v2";
const SHELL = ["/", "/index.html", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  // Other sites' responses (map images, fonts, sign-in) are theirs to cache.
  if (new URL(request.url).origin !== self.location.origin) return;
  // Never cache API calls — always go to the network.
  if (request.url.includes("/api/")) return;
  if (request.method !== "GET") return;

  e.respondWith(
    fetch(request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
        return res;
      })
      .catch(() => caches.match(request).then((r) => r || caches.match("/")))
  );
});
