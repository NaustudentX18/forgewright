/* forgewright service worker
 *
 * App shell + last-session cache. Bypasses the SW for POST requests so
 * SSE streaming on /api/sessions/{id}/messages works exactly as it does
 * without a SW. Caches GETs of /, /static/*, and the read-only session
 * endpoints so a phone that's lost Wi-Fi can still reopen and read its
 * most recent chat.
 *
 * Strategy:
 *   install   — precache the static app shell into forgewright-shell-v1
 *   activate  — drop the old cache if the version bumped, claim clients
 *   fetch:
 *     POST anything  → bypass (return without respondWith)
 *     GET /, /static → cache-first, fall back to network
 *     GET /api/sessions, /api/sessions/{id} → network-first, fall back
 *                                              to the last good cached
 *                                              copy
 *     everything else → network only
 *
 * Bumping CACHE_NAME invalidates the old shell on next activate.
 */

const CACHE_NAME = "forgewright-shell-v1";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/favicon.png",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/apple-touch-icon.png",
  "/static/icon-maskable-512.png",
];

const OFFLINE_HTML =
  '<!doctype html><meta charset="utf-8"><meta name="viewport" ' +
  'content="width=device-width, initial-scale=1, viewport-fit=cover">' +
  '<title>forgewright — offline</title><style>body{background:#020617;' +
  'color:#F8FAFC;font:450 16px/1.5 -apple-system,BlinkMacSystemFont,' +
  '"Segoe UI",Roboto,sans-serif;margin:0;padding:24px;display:flex;' +
  'min-height:100vh;align-items:center;justify-content:center;text-align:center}' +
  "main{max-width:480px}h1{font-size:22px;margin:0 0 8px}p{color:#94A3B8;" +
  "margin:0 0 16px}button{background:#22C55E;color:#020617;border:0;" +
  'border-radius:8px;padding:10px 16px;font:600 14px/1 inherit;cursor:pointer}</style>' +
  '<main><h1>forgewright is offline</h1><p>Reconnect to load your chats. ' +
  'The most recent session will appear here when you\'re back.</p>' +
  '<button onclick="location.reload()">Try again</button></main>';

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      // addAll fails atomically if any URL 404s. Precache each URL
      // independently so a single missing asset does not brick the SW.
      await Promise.all(
        SHELL.map((url) =>
          cache.add(url).catch((err) => {
            // Logged but non-fatal — the SW still installs and the
            // missing asset falls back to the network on fetch.
            console.warn("sw.precache.skip url=" + url, err);
          }),
        ),
      );
      self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k.startsWith("forgewright-shell-") && k !== CACHE_NAME)
          .map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

function isStaticAsset(url) {
  return url.pathname.startsWith("/static/");
}

function isSessionGet(url) {
  if (url.pathname === "/api/sessions") return true;
  // /api/sessions/{id} but NOT /api/sessions/{id}/messages or /abort
  if (url.pathname.startsWith("/api/sessions/")) {
    const rest = url.pathname.slice("/api/sessions/".length);
    return !rest.includes("/");
  }
  return false;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") {
    // POST/PUT/DELETE bypass — preserves SSE streaming for message sends.
    return;
  }
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Navigation request for the app shell.
  if (req.mode === "navigate" || url.pathname === "/") {
    event.respondWith(handleShell(req));
    return;
  }

  // Static assets: cache-first.
  if (isStaticAsset(url)) {
    event.respondWith(handleStatic(req));
    return;
  }

  // Read-only session GETs: network-first with last-good fallback.
  if (isSessionGet(url)) {
    event.respondWith(handleSession(req));
    return;
  }

  // Everything else (POSTs, /api/health, etc.) — network only, no
  // SW involvement.
});

async function handleShell(req) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const response = await fetch(req);
    // Only cache successful 200 responses; never cache redirects or errors.
    if (response.ok) cache.put(req, response.clone());
    return response;
  } catch (err) {
    // Network is gone — return the offline page.
    return new Response(OFFLINE_HTML, {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }
}

async function handleStatic(req) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const response = await fetch(req);
    if (response.ok) cache.put(req, response.clone());
    return response;
  } catch (err) {
    // If a static asset is missing and we are offline, return an empty
    // 504 so the page does not hang. The app shell itself falls back
    // to the OFFLINE_HTML above.
    return new Response("", { status: 504, statusText: "offline" });
  }
}

async function handleSession(req) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(req);
    if (response.ok) cache.put(req, response.clone());
    return response;
  } catch (err) {
    const cached = await cache.match(req);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}
