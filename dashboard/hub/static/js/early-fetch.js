// Start a page's data requests while its HTML is still parsing.
//
// Every Hub page asks for its data from deferred JSX, so the "loading…" state
// waited on the scripts first: 100 to 960 ms on localhost (home was the worst)
// before the first /api/ request even left. This script runs from the <head>,
// replays the same-origin JSON GETs this page made during its last load, and
// hands each in-flight request to the page's own fetch() of the same URL.
//
// This is a live request started earlier, never a saved copy, so it keeps the
// network-first rule in CLAUDE-hub-offline.md: the page only ever sees an answer
// the server gave on this load. A replayed request nobody claims is dropped;
// a failed one makes the page's fetch go to the network as it always did.
//
// ponytail: learns the list from the last load instead of a per-page manifest,
// so no list drifts out of step with the pages. Ceiling: a URL that changes
// every load is replayed once for nothing; add an exclusion if one ever does.
(function () {
  if (!window.fetch || !window.Promise || window.__hubEarly) return;
  window.__hubEarly = true;
  var KEY = "hub-early:" + location.pathname + location.search;
  var MAX = 8;              // replays per page, so a chatty page cannot fan out
  var LEARN_MS = 15000;     // only fetches made this soon after load are "load" fetches
  var ADOPT_MS = 6000;      // a replay unclaimed by then is not this load's request
  var t0 = Date.now();
  var native = window.fetch.bind(window);
  var inflight = {};
  var learned = [];
  var wrote = false;

  function sameOriginPath(input) {
    var raw = typeof input === "string" ? input : input && input.url;
    if (!raw) return null;
    try {
      // baseURI, not location: Forge pages set <base href="/forge/"> and fetch
      // "api/stats" from /forge/c/X/role/build, so location learned a URL that 404s
      var u = new URL(raw, document.baseURI || location.href);
      if (u.origin !== location.origin || u.pathname.indexOf("/api/") < 0) return null;
      return u.pathname + u.search;
    } catch (e) { return null; }
  }

  function plainGet(input, init) {
    var method = (init && init.method) || (typeof input === "object" && input.method) || "GET";
    return method.toUpperCase() === "GET" && !(init && init.body);
  }

  function remember(path, resp) {
    if (wrote || Date.now() - t0 > LEARN_MS || learned.length >= MAX || learned.indexOf(path) >= 0) return;
    var ctype = (resp.headers.get("Content-Type") || "").split(";")[0];
    if (!resp.ok || ctype !== "application/json") return;
    learned.push(path);
    try { localStorage[KEY] = JSON.stringify(learned); } catch (e) {}
  }

  var list = [];
  // Read then cleared: the list is rebuilt from this load alone, so a URL the
  // page stopped asking for falls out the next time round.
  try {
    list = JSON.parse(localStorage[KEY] || "[]").slice(0, MAX);
    localStorage.removeItem(KEY);
  } catch (e) {}
  list.filter(function (p) {
    return typeof p === "string" && p.charAt(0) === "/" && p.charAt(1) !== "/";
  }).forEach(function (path) {
    inflight[path] = native(path, { credentials: "same-origin" }).catch(function () { return null; });
  });

  window.fetch = function (input, init) {
    var get = plainGet(input, init);
    // A write means any later read must see it, so a replay still waiting would
    // be an answer from before the edit. Same for one claimed long after load.
    // Reads after a write depend on it, so they are not learned either (the jc
    // sweep follows a run POST and would be replayed for nothing every load).
    if (!get) wrote = true;
    if (!get || Date.now() - t0 > ADOPT_MS) inflight = {};
    var path = get && sameOriginPath(input);
    if (!path) return native(input, init);
    var early = inflight[path];
    delete inflight[path];
    var p = early
      ? early.then(function (r) { return r || native(input, init); })
      : native(input, init);
    return p.then(function (r) { remember(path, r); return r; });
  };
})();
