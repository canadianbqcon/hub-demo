# CLAUDE-hub-offline.md — the Hub's two offline paths [BINDING]

Split out of `dashboard/CLAUDE.md` 2026-08-30 at the 250-line ceiling. Both rules were
added the same day, answering the same question from two directions: what the Hub shows
when it cannot reach something. Read this alongside the **Hub asset pipeline** section in
`dashboard/CLAUDE.md`, which is where the vendored-libs and server-side-JSX rules live and
which both of these are built to preserve.

The shared principle, and the thing to not undo: **ask first, fall back only on a real
failure.** Neither path ever prefers a saved copy for speed, and neither hides a breakage
behind old data that looks live.

## Phone off the tailnet — the service worker

**The offline service worker (`hub/static/js/sw.js`, added 2026-08-30) is network-first, and
must stay that way.** It exists so the installed home-screen Hub still reads on a phone that is
off the tailnet — it keeps whatever that phone last loaded and serves it back only when a fetch
genuinely fails. Cache-first, or a precache manifest, would trade away the "an edit is never
masked" guarantee the asset-pipeline rules are built around, so don't. It is served from `/sw.js`
(root scope; a worker under `/static/` could only control `/static/`) and registered from
`_HEAD_TAGS` in `app.py`, alongside the manifest link. Non-GET and cross-origin are skipped, so
writes fail offline instead of looking saved, and map tiles never fill the cache. The reader is
told the page is a saved copy by the stale banner in `App.jsx`, which fires off `GENERATED_AT`.
Registration needs a secure context: `https://<machine>.ts.net` (the `tailscale serve --https=443`
mapping) works, a bare `http://100.x.x.x:5002` does not. Checks: `hub/tests/test_offline_sw.py`.

**Three additions from 2026-09-18 (Lost Lands, no signal inside the venue), none of which
changes network-first.** Each came from driving the real page in Chrome with the network cut:

- **A hung fetch counts as a failed one.** A festival crowd leaves a phone with bars and no
  throughput, so the fetch neither fails nor finishes. After `SLOW_MS` (6s) the worker serves
  the kept copy and lets the request finish behind it, still updating the copy. With nothing
  kept it keeps waiting. A frame load whose referrer is not a Hub page (a foreign page
  framed in the Viewer that redirects to the Hub) is network-only, so `app.py`
  `_refuse_cross_site_framing` always runs; the answer is still kept, and Hub-started
  frames (the warmer's, trip previews) keep this fallback. Check: `hub/tests/sw.selftest.js`
  cases 12-13. The Hub's own `/api/` calls are exempt and always wait: `/api/home`
  measured 4 to 17s from a hotel link with a healthy server, and saved money numbers shown
  because the server was slow is the masking this file forbids. `/trips/api/` is not exempt.
- **The kept copy is matched with `ignoreVary`.** The pages send `Vary: Cookie`, and a plain
  `caches.match` refuses a copy stored under a different cookie header, so a rotated session
  cookie would have emptied the cache in the field without a trace.
- **Field pages are saved ahead of time.** "Keeps what the phone last loaded" meant a page
  never opened online was a browser error offline. `_HEAD_SCRIPTS` in `app.py` now loads each
  `_OFFLINE_WARM` page once in a hidden frame from any Hub page opened online, at most every
  30 minutes per browser. The frames load side by side, live 90s, and the throttle is stamped
  only when they come down. A frame closed 6s after its load event passed on localhost and
  failed against the real PC over a hotel link, where the trip data and the map were still
  downloading: test this against the tailnet address, never only localhost. The frame runs the page for
  real, so there is no url list to keep in step, which is the objection to a precache manifest
  above and still stands. A hallmark page must fetch its field assets at load, not on first tab
  open (`lostlands.js` does this for the festival map), or the frame never sees them. The
  scripts are injected on every page, including the trips templates that keep their own
  manifest; those used to be skipped whole and so never registered the worker.

`app.py` is Python, so that last part needs a Hub restart to go live; `sw.js` and the
hallmark modules are read per request and do not.

**The open Lost Lands page has its own copy of the worker, scoped to itself (2026-09-18).**
`trips/public_app.py` serves the same `sw.js` at `/lostlands/<key>/sw.js`, so its scope is that
one page. The gated guest board on the public site deliberately gets NO worker: a guest whose
code is revoked must not keep a saved copy of a board they can no longer open. Do not move that
worker to the public root to "cover everything".

## Desktop with no route out — the last-good cache

**The last-good cache in `home_data.py` (`_last_good`/`_online`/`_cached_at`, added 2026-08-30)
serves a saved copy of the calendar, subscriptions and card balances, but ONLY when a TCP probe
says the box has no network.** That narrowness is the design, not an optimisation. gcal and ynab
swallow their own failures and return `[]`, so if the cache were consulted on any empty result,
an expired Google login or a dead YNAB token would render plausible old numbers indefinitely and
never get noticed. Blank has to keep meaning broken whenever the box is online. Only a non-empty
result is written, so one bad refresh cannot overwrite a good copy; `CACHED_AT` in the payload is
non-null exactly when a saved copy is being served, and drives the second wording of the App.jsx
banner. Checks: `hub/tests/test_last_good_cache.py`.

## Early fetch: starting a page's requests sooner, not answering from a copy

**`hub/static/js/early-fetch.js` (added 2026-10-22) is injected into every page head by
`_HEAD_SCRIPTS` in `app.py`.** It replays the same-origin `/api/` JSON GETs the page made on
its last load while the HTML is still parsing, and the page's own `fetch()` of the same URL
adopts the in-flight request. It never serves a saved body: the list of URLs is the only thing
it remembers, so it sits inside the rule above. Three limits keep it honest: a replay is
handed out once, only within 6s of load, and any non-GET drops every replay still waiting and
stops learning for that load (reads after a write depend on the write). Measured on localhost:
first data request 40-120ms after navigation on every data page, from 120-960ms. It is on
`public_area.SHARED_STATIC` and the trips mirror's `_STATIC_ALLOW` because the login page
carries it too. Check: `hub/tests/early-fetch.selftest.js`.
