// Service worker — caches the app shell so the installed PWA works offline.
// Bump CACHE_VERSION whenever the app files change so clients fetch fresh copies.
const CACHE_VERSION = "pbp-v9";
const ASSETS = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./data.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png",
];

// Let the page ask which cache version is actually running, so the About panel
// can display it (a quick way to confirm a fresh shell vs. a stale cached one).
self.addEventListener("message", (event) => {
  if (event.data === "get-version" && event.source) {
    event.source.postMessage({ type: "version", version: CACHE_VERSION });
  }
});

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch strategy, offline-first throughout:
//   * Page navigations  -> CACHE-FIRST: serve the cached shell immediately so
//     the app always opens instantly with the laptop off. (Network-first here
//     was the bug: a hanging request to the dead server left a blank screen.)
//   * data.js           -> try network with a short timeout for freshness, then
//     fall back to cache — never blocks on a dead/slow connection.
//   * everything else    -> cache-first, then network.
// Cross-origin (the forecast API) is left to the network, never cached.

// fetch() that rejects after `ms` instead of hanging on a half-open connection.
function fetchWithTimeout(req, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), ms);
    fetch(req).then(
      (res) => { clearTimeout(timer); resolve(res); },
      (err) => { clearTimeout(timer); reject(err); }
    );
  });
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  if (new URL(req.url).origin !== self.location.origin) return;

  // Navigation: serve the cached shell first; only touch the network if it's
  // somehow not cached yet.
  if (req.mode === "navigate") {
    event.respondWith(
      caches.match("./index.html")
        .then((c) => c || caches.match("./"))
        .then((c) => c || fetch(req))
        .catch(() => caches.match("./index.html"))
    );
    return;
  }

  const isData = new URL(req.url).pathname.endsWith("data.js");

  if (isData) {
    event.respondWith(
      fetchWithTimeout(req, 3000).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
        return res;
      });
    })
  );
});
