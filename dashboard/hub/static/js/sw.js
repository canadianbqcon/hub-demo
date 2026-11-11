/* Service worker — makes the Hub readable when the server is out of reach.

   The Hub is a Flask app on the house machine, so a phone off the tailnet (plane,
   subway, dead zone) gets the browser's error page even though it is installed to
   the home screen — the manifest made it launchable, nothing made it survivable.
   This keeps a copy of whatever the phone last loaded and hands that back when the
   network fails.

   Strategy is network-first, cache-as-fallback, for every same-origin GET. Not
   cache-first, and not a precache manifest, both on purpose:

   - Network-first preserves the app's "an edit is never masked" guarantee. Online,
     every response still comes from the server, so a changed asset, a changed shell
     and fresh /api/home all land on a plain reload exactly as they do today. Only a
     genuinely failed fetch is answered from the cache.
   - No precache list, because there is nothing to keep in sync. Whatever the phone
     actually loaded is what it has offline; assets it never asked for it never
     needed. The versioned `?v=<mtime>` URLs (see _stamp_asset_versions in app.py)
     mean an edited file is a new cache key, so stale entries are never consulted
     again — they just sit there until the eviction below clears them.

   Writes (task completion, edits) are GET-skipped and so fail offline as they
   should. The stale banner in App.jsx is what tells the reader the page is a saved
   copy, off GENERATED_AT in the cached payload.

   A signal too weak to answer is treated like no signal (2026-09-18, Lost Lands:
   a festival crowd leaves the phone with bars and no throughput, so the fetch
   neither fails nor finishes and the page hangs on a copy it already holds).
   After SLOW_MS a kept copy is served; the request carries on behind it and its
   answer still replaces the copy. With nothing kept, the wait simply continues.
   Online on a working link nothing changes: the server answers first.
   The Hub's own /api/ calls are exempt and wait as long as they need: /api/home
   measured 4 to 17s from a hotel link with the server perfectly healthy, and its
   panels are live money and calendar numbers, where a saved copy shown because
   the server was merely slow is exactly the masking this file refuses. The trips
   data under /trips/api/ is not exempt; it measured 1 to 4s on that same link.

   ponytail: one cache, one fetch handler, no library. Bump CACHE to force a purge.
*/
const CACHE = "hub-v1";
const SLOW_MS = 6000;

// The pages send `Vary: Cookie`, and a plain match refuses a copy whose cookie
// header differs from the one it was stored under. A session cookie rotating
// between the last online load and the field would silently empty the cache.
const kept = (req) => caches.match(req, { ignoreVary: true });

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((n) => n !== CACHE).map((n) => caches.delete(n))
      ))
      // mail and bell lists kept before /mail/ and /notify/ were exempted come out too
      .then(() => caches.open(CACHE))
      .then((c) => c.keys().then((reqs) => Promise.all(
        reqs.filter((r) => /^\/(mail|notify)\//.test(new URL(r.url).pathname)).map((r) => c.delete(r))
      )))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  // Non-GET is a write and has no meaningful offline answer. Cross-origin is map
  // tiles and the like — passing those through unhandled lets the browser do its
  // own thing rather than filling our cache with someone else's bytes.
  if (req.method !== "GET") return;
  if (new URL(req.url).origin !== self.location.origin) return;
  // Mail is private and only useful live, so none of it lands in the phone's Cache Storage.
  // The bell's list is live state too: a cached copy would show read rows as unread and hide
  // the "unavailable" state its fail-open rule depends on.
  if (/^\/(mail|notify)\//.test(new URL(req.url).pathname)) return;

  const patient = new URL(req.url).pathname.startsWith("/api/");
  const net = fetch(req).then((resp) => {
    // Only successful, complete responses are worth keeping. A 206 cannot go
    // in the Cache API at all, and caching a 404/500 would serve that error
    // back forever once the network drops.
    if (resp.ok && resp.type === "basic") {
      const copy = resp.clone();
      e.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy)));
    }
    return resp;
  });
  // Keeps the worker alive for a late answer after a kept copy was served, and
  // stops that late failure surfacing as an unhandled rejection.
  e.waitUntil(net.catch(() => {}));

  // A frame a foreign page started is answered by the server, never a kept copy:
  // app.py refuses a Hub page there (_refuse_cross_site_framing), and a kept copy
  // would skip that check. The Hub's own frames carry a Hub referrer, which a
  // foreign page cannot forge, and keep the offline fallback. The answer is still kept.
  // A foreign server's redirect keeps the referrer of the frame's first request, so this
  // relies on the Viewer's iframe sending none (referrerPolicy="no-referrer" in viewer.jsx).
  if (["iframe", "frame", "object", "embed"].includes(req.destination)
      && !(req.referrer || "").startsWith(self.location.origin + "/")) {
    e.respondWith(net);
    return;
  }

  e.respondWith(
    Promise.race([net, new Promise((r) => patient || setTimeout(r, SLOW_MS))])
      // Timer won: a kept copy now, else keep waiting on the network.
      .then((resp) => resp || kept(req).then((hit) => hit || net))
      // A miss here means this page was never visited while online, so there is
      // nothing honest to show. Letting it reject gives the browser's own offline
      // page, which is clearer than serving some other page's HTML in its place.
      .catch(() => kept(req).then((hit) => hit || Promise.reject()))
  );
});
