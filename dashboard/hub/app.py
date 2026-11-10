if __import__("os").environ.get("DEMO_MODE") == "1":
    import demo_mode; demo_mode.cut()
"""
hub home dashboard — port 5002.
serves the home panel with real vault data.
independent of the trips/jobs/purchases dashboard at port 5001.
"""

import gzip
import hashlib
import hmac
import json
import os
import re
import socket
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from datetime import timedelta
from pathlib import Path

from werkzeug.serving import WSGIRequestHandler, make_server
from flask import (
    Flask,
    abort,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# --- parent-dir imports (gcal, gmail, ynab live in dashboard/) ---
# hub/ MUST be searched before dashboard/ on sys.path: hub-local packages can
# share a top-level name with a legacy package in dashboard/ (e.g. `purchases`
# exists both as dashboard/hub/purchases and the legacy dashboard/purchases), and
# the hub copy must win. The old conditional inserts had a launch-mode bug: when
# run as `python3 app.py`, Python already seeds sys.path[0] with hub/'s absolute
# path, so the "not in sys.path" guard skipped re-inserting hub/ while dashboard/
# still got inserted at 0 — landing AHEAD of hub/ and shadowing hub/purchases with
# the legacy one. Rebuild the order explicitly so hub/ is always first.
_DASHBOARD = Path(__file__).parent.parent
_HUB_DIR = Path(__file__).parent  # also home of tasks.py, the canonical task store
for _p in (str(_DASHBOARD), str(_HUB_DIR)):
    while _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_DASHBOARD))
sys.path.insert(0, str(_HUB_DIR))  # inserted last → ends up first

# load dashboard/.env (same file used by port 5001)
_env_file = _DASHBOARD / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

import sqlite_helpers
import briefing_snapshot
import config
import gcal
import gdocs
import gdrive
import gmail
import gsheets
import scheduler as skill_scheduler
import tasks
import transit
import wx_extras

from barback import api as barback_api
from barback import db as barback_db
from batch_prep import api as batch_prep_api
from batch_prep import db as batch_prep_db
from jc import api as jc_api
from jobs import api as jobs_api
from jobs import db as jobs_db
from jobs import submitter as jobs_submitter
from vault_map import api as vault_map_api
from vault_map import db as vault_map_db
from capabilities import api as capabilities_api
from blueprints import api as blueprints_api
from artifacts import api as artifacts_api
from viewer import api as viewer_api
from forge import api as forge_api
from workbench import api as workbench_api
from marks import api as marks_api
from trips import api as trips_api
from trips import db as trips_db
from purchases import api as purchases_api
from purchases import db as purchases_db
from checklists import api as checklists_api
from checklists import db as checklists_db
from work import api as work_api
from finances import api as finances_api
from finances import db as finances_db
from finances import owed as finances_owed
from ledger import api as ledger_api
from ledger import db as ledger_db
from stocks import api as stocks_api
from stocks import db as stocks_db
from food import api as food_api
from food import db as food_db
from automations import api as automations_api
from inventory import api as inventory_api
from mail import api as mail_api
from news import api as news_api
from news import db as news_db

from recipes import api as recipes_api

app = Flask(__name__)
if os.environ.get("DEMO_MODE") == "1":
    import demo_mode; demo_mode.install(app)
# Re-read Jinja templates from disk on every request even though we run debug=False.
# Without this, render_template() (jobs.html, trips, home) compiles once at startup and
# caches in memory, so HTML edits silently don't appear until a restart — while static
# CSS/JS (cache-busted) update immediately. That split served stale markup under fresh
# styling. See wiki/problems/vesper-template-cache-stale-html.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
# The above only covers Jinja templates + static assets. Python module code
# (db.py, api.py, any blueprint) is imported once at process start and never
# re-read — a running Hub process holds the pre-edit module in memory until
# manually restarted. Cost a session a full round misdiagnosing "the
# checkboxes don't save" as a frontend bug, when db.py's field whitelist had
# already been fixed on disk. See wiki/problems/hub-backend-edit-needs-restart.


@app.teardown_request
def _release_sqlite(_exc):
    """Hand back this request's SQLite connections.

    sqlite_helpers.connect() keeps one connection per database per THREAD so the
    dozen-plus opens a single request makes collapse into one. Werkzeug gives each
    request its own thread, so this teardown is what keeps "per thread" from
    quietly meaning "forever" as threads accumulate.
    """
    sqlite_helpers.close_scoped()


@app.after_request
def _no_cache_static(resp):
    # Force browsers to re-fetch JS/CSS every load so an edit is never masked by a
    # stale cached asset. Match on the ENDPOINT, not the path: the hub app
    # (dashboard/api.py) checks request.path.startswith("/static/"), which only
    # catches root static and would MISS blueprint assets — batch_prep serves
    # batch.js/batch.css at /batch/static/, jobs at /jobs/static/. Flask names the
    # root static endpoint "static" and every blueprint's "<bp>.static", so the
    # suffix test below covers all of them. This is the bug behind the stale
    # batch.js/batch.css that served old code after edits.
    # See wiki/problems/vesper-template-cache-stale-html.
    # no-cache, NOT no-store: both forbid serving a stale asset without asking,
    # but no-store also forbids KEEPING it, so every load re-downloaded the whole
    # file. send_file already stamps an ETag, so no-cache revalidates and gets a
    # 304 back when nothing changed — same freshness promise, none of the bytes.
    # The forge catalog alone is 424 KB that was being re-sent on every page view.
    # /static/vendor/ is the exception: pinned third-party builds (react 18.3.1,
    # @babel/standalone 7.26.4) vendored out of unpkg so the tailnet dashboard does
    # not need the public internet to render. A pinned build never changes under the
    # same filename, so it gets the immutable treatment the CDN gave it — otherwise
    # every load revalidates 3 MB of babel for a guaranteed 304. Bump the filename
    # (or the version in it) when upgrading; do not edit a vendored file in place.
    if request.path.startswith("/static/vendor/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.endpoint and request.endpoint.rsplit(".", 1)[-1] == "static":
        # A `?v=` that still matches the file on disk cannot be stale, so the
        # browser has no reason to ask again — see _stamp_asset_versions below,
        # which is what puts the current mtime in the URL. Anything else (no
        # version, or one that no longer matches) falls back to revalidating.
        want = request.args.get("v")
        if want and want == _asset_token(request.path):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache, max-age=0"
    return resp


# Where each /<prefix>/static/ URL actually lives on disk. Flask already knows —
# the root app plus one static folder per blueprint — so this reads it off the
# app rather than keeping a second copy of the layout in sync by hand.
def _static_roots() -> list[tuple[str, Path]]:
    global _STATIC_ROOTS
    if _STATIC_ROOTS is None:
        roots = []
        if app.static_folder:
            roots.append(((app.static_url_path or "").rstrip("/") + "/", Path(app.static_folder)))
        for bp in app.blueprints.values():
            if bp.static_folder:
                prefix = (bp.url_prefix or "") + (bp.static_url_path or "/static")
                roots.append((prefix.rstrip("/") + "/", Path(bp.static_folder)))
        # longest prefix first: /trips/static/ must win over /static/
        _STATIC_ROOTS = sorted(roots, key=lambda r: -len(r[0]))
    return _STATIC_ROOTS


_STATIC_ROOTS = None


def _asset_token(url_path: str) -> str | None:
    """The current version of whatever a URL serves, or None if it is not ours.

    An mtime for a real file. /hub-modules.js is generated rather than stored, so
    it answers with a hash of the module list it would serve — same contract, and
    it means the one script every page loads stops costing a round trip each time.
    """
    # /jsx/<rel> is transpiled from the source file at JSX_ROOT/<rel> (see the _jsx
    # route). Resolve it the same way that route does — some modules keep their JSX
    # under frontend/static/, which is not a Flask static root, so the loop below
    # would miss them. This is what lets every JSX file be mtime-versioned and cached.
    if url_path.startswith("/jsx/"):
        src = (JSX_ROOT / url_path[len("/jsx/"):]).resolve()
        if src.suffix == ".jsx" and src.is_file() and src.is_relative_to(JSX_ROOT):
            return str(int(src.stat().st_mtime))
        return None
    if url_path == "/hub-modules.js":
        # EXPOSED rides in the same script (it drives the bar's sign-out), so it is
        # part of the hash or a flipped gate would sit behind an immutable cache.
        return hashlib.md5(json.dumps([_MODULES, EXPOSED], sort_keys=True).encode(), usedforsecurity=False).hexdigest()[:12]
    for prefix, folder in _static_roots():
        if url_path.startswith(prefix):
            rel = url_path[len(prefix):]
            if not rel or ".." in rel:
                return None
            try:
                return str(int((folder / rel).stat().st_mtime))
            except OSError:
                return None
    return None


# `?v=` is optional on purpose: an unversioned ref gets one stamped on rather
# than revalidating on every page change forever, which is what favicon.png (on
# all 25 templates) and /hub-modules.js (on 15) were doing.
_ASSET_REF = re.compile(
    rb'((?:href|src)=")(/[^"?]+\.(?:jsx|js|css|png|svg|ico|webmanifest))(?:\?v=[^"]*)?(")')


_GZ_MEMO: "OrderedDict[str, bytes]" = OrderedDict()
_GZ_MEMO_MIN = 64 * 1024     # small bodies compress in well under a millisecond
_GZ_MEMO_MAX = 32
_GZ_LOCK = threading.Lock()


def _gzip_bytes(data: bytes, etag: str | None) -> bytes:
    """gzip.compress, remembered by the body's ETag for the big ones.

    Every load re-compressed byte-identical bodies: the vault tree is 18.6 MB and
    cost ~550 ms of compression per request inside the Hub, the home payload
    ~25 ms. Every JSON body already carries an md5 ETag of its content by now
    (_conditional_json runs first), so the tag is a safe key: same tag, same
    bytes. The len check guards an ETag that is not a content hash.

    ponytail: 32-entry LRU in the process, no size cap beyond the count. Bound it
    by bytes if a module ever ships many multi-MB bodies.
    """
    if not etag or len(data) < _GZ_MEMO_MIN:
        return gzip.compress(data, 6)
    key = f"{etag}:{len(data)}"
    with _GZ_LOCK:
        hit = _GZ_MEMO.get(key)
        if hit is not None:
            _GZ_MEMO.move_to_end(key)
            return hit
    out = gzip.compress(data, 6)
    with _GZ_LOCK:
        _GZ_MEMO[key] = out
        while len(_GZ_MEMO) > _GZ_MEMO_MAX:
            _GZ_MEMO.popitem(last=False)
    return out


@app.after_request
def _gzip_response(resp):
    """Compress text on the way out.

    Nothing else in the stack did, so the forge editor shipped roughly a megabyte
    of JSON and base64 icons in the clear on every load; the same bytes gzip to
    about a seventh of that, which is the difference between "slow" and "instant"
    over the tailnet.

    ponytail: stdlib gzip in one hook, no flask-compress dependency. The ETag is
    deliberately left alone — suffixing it the way flask-compress does would make
    the browser send back a tag Flask's own conditional check no longer
    recognises, and every 304 above would turn back into a 200.
    """
    if (not 200 <= resp.status_code < 300
            or "Content-Encoding" in resp.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "")):
        return resp
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    # event-stream is text/ and must NOT be buffered — jobs/api.py streams research
    # tokens down one, and reading it whole here would hold the whole answer back.
    if ctype == "text/event-stream" or not ctype.startswith(
            ("text/", "application/json", "application/javascript",
             "application/xml", "image/svg+xml")):
        return resp
    resp.direct_passthrough = False   # send_file hands back a file wrapper
    data = resp.get_data()
    if len(data) < 1024:              # the gzip header costs more than the saving
        return resp
    resp.set_data(_gzip_bytes(data, resp.get_etag()[0]))
    resp.headers["Content-Encoding"] = "gzip"
    resp.vary.add("Accept-Encoding")
    return resp


@app.before_request
def _refuse_cross_site_framing():
    """No Hub page loads in a frame that a foreign page put it in.

    The Viewer frames web pages Claude shows with scripts and their own origin
    allowed. One that redirects or navigates its frame to the Hub would land a
    Hub page there, same-origin with the Hub tab around it, free to lift its
    sandbox and drive the Hub. The browser marks such a request
    Sec-Fetch-Site: cross-site (or same-site, for another port on this host);
    the Hub framing itself is same-origin. sw.js leaves frame loads to the
    network so a kept copy cannot skip this.
    """
    if (request.headers.get("Sec-Fetch-Dest") in ("iframe", "frame", "object", "embed")
            and request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site")):
        # worded for the Viewer, which shows this when a Hub address it does not know as
        # local (tailnet name, LAN IP) lands in its frame
        return "Hub pages open in their own tab.", 403


_PAGE_CONDITIONALS = ("HTTP_IF_NONE_MATCH", "HTTP_IF_MODIFIED_SINCE")
_DEFERRED = "hub.deferred_conditionals"


@app.before_request
def _defer_page_conditionals():
    """Keep send_file from answering a page navigation's revalidation itself.

    Pages come off disk through send_from_directory, which compares the browser's
    If-None-Match against the template file's own tag and answers 304 before any
    after_request hook runs. That tag knows nothing about the assets the page
    names, so it was 304 for a page whose stamped links had changed (see
    _stamp_asset_versions). Holding the two headers back here, and handing them
    to that hook once the body is final, moves the decision to the only place
    that can make it correctly. Scoped to navigations (Sec-Fetch-Dest: document,
    or an Accept that leads with text/html) so asset and JSON revalidation is
    untouched. A navigation to something that turns out not to be stamped HTML
    just gets a 200 instead of a 304, which is the safe side.
    """
    env = request.environ
    if (env.get("HTTP_SEC_FETCH_DEST") == "document"
            or env.get("HTTP_ACCEPT", "").startswith("text/html")):
        held = {k: env.pop(k) for k in _PAGE_CONDITIONALS if k in env}
        if held:
            env[_DEFERRED] = held


@app.after_request
def _stamp_asset_versions(resp):
    """Rewrite every `?v=` in an HTML page to the asset's current mtime.

    The templates carry hand-written version numbers (`trips.js?v=100`), which
    only bust a cache if somebody remembers to bump one. Nobody reliably does,
    which is why every static asset was served `no-cache` and every navigation
    re-asked the server about all twenty of them. Those questions are the bulk of
    what a page change costs: on localhost 24 requests are free, but over the
    tailnet at ~40 ms each they were ~500 ms in front of first paint.

    Stamping the mtime instead makes the URL change exactly when the file does,
    so `_no_cache_static` above can hand back `immutable` and the browser stops
    asking. An edit still shows up on the next load — the page it is referenced
    from is rendered fresh (TEMPLATES_AUTO_RELOAD) and names the new URL — so
    this keeps the "an edit is never masked" guarantee rather than trading it
    away for the speed. A path that resolves to no file keeps whatever version
    the template wrote, and keeps revalidating.

    ponytail: a stat per asset per page render rather than a cache to invalidate.
    The stat IS the invalidation. On /mnt/c a stat is ~10ms, not sub-millisecond,
    so the stats run in a thread pool: 14 serial stats were ~150ms of every page.
    """
    if (resp.status_code != 200
            or resp.headers.get("Content-Type", "").split(";")[0].strip() != "text/html"):
        return resp
    # A page served straight off disk (send_from_directory — the vault map is one)
    # is still HTML whose asset ?v= must be stamped. Without clearing the file-wrapper
    # flag it skips versioning entirely, so all of its css/js revalidate on every load.
    resp.direct_passthrough = False

    data = resp.get_data()
    paths = list({m.group(2).decode("utf-8", "replace") for m in _ASSET_REF.finditer(data)})
    with ThreadPoolExecutor(max_workers=16) as pool:
        tokens = dict(zip(paths, pool.map(_asset_token, paths), strict=False))

    def _swap(m):
        token = tokens[m.group(2).decode("utf-8", "replace")]
        if token is None:
            return m.group(0)
        return m.group(1) + m.group(2) + b"?v=" + token.encode() + m.group(3)

    body, n = _ASSET_REF.subn(_swap, data)
    if n:
        resp.set_data(body)
        # The validator must cover the stamped body, not just the template file.
        # send_from_directory tags the page with the template's mtime, so a browser
        # that already held /blueprints/ revalidated, got 304 for an unchanged
        # template, and kept its cached copy, whose links still named the OLD ?v=
        # URL for blueprints.css, which the browser holds immutable. A CSS-only
        # edit therefore never reached an open browser; 2026-09-10, the scroll fix
        # was live on the server and invisible in Chrome. Hashing the final bytes
        # makes the tag change whenever any stamp, the template, or an injected
        # head tag changes. _defer_page_conditionals above holds the browser's
        # validators back from send_file's own file check and hands them to this
        # hook, so the decision is made against this tag and nothing else.
        # Last-Modified goes too: it described the template file, not this body.
        resp.set_etag(hashlib.md5(body, usedforsecurity=False).hexdigest())
        resp.headers.pop("Last-Modified", None)
        request.environ.update(request.environ.pop(_DEFERRED, {}))
        resp.make_conditional(request)
    return resp


# Pages saved to the phone ahead of time; see the warm script in _HEAD_SCRIPTS.
_OFFLINE_WARM = ["/trips/", "/trips/59"]

# The one <link> Safari reads for Add to Home Screen. It ignores favicon.png for
# that, so without this iOS pins a screenshot of the page instead of the mark.
_ICON_LINK = re.compile(rb'(<link rel="icon"[^>]*>)')
_HEAD_TAGS = (
    b'\n<link rel="apple-touch-icon" href="/static/assets/apple-touch-icon.png">'
    b'\n<link rel="manifest" href="/static/assets/manifest.webmanifest">'
    # Home-screen app: without this iOS paints a black band under the notch and
    # starts the page below it. Translucent lets the wallpaper run to the top
    # edge; the bar pads itself by --safe-t (theme-switch.js) to clear the clock.
    b'\n<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
)
# Split from the links above 2026-09-18: the trips templates declare their own
# manifest and so were skipped whole, which left a phone that only ever opens
# /trips with no worker at all. The links stay conditional, the scripts do not.
_HEAD_SCRIPTS = (
    # Starts the page's data GETs during parse instead of after the deferred JSX
    # runs; see the file header. Plain src so _stamp_asset_versions versions it
    # and the browser holds it immutable: no round trip after the first load.
    b'\n<script src="/static/js/early-fetch.js"></script>'
    # The manifest above only makes the Hub launchable from a home screen; without
    # a worker, launching it off the tailnet gets the browser's error page. One
    # registration from any page covers the whole origin, so it rides along here
    # rather than in 24 template heads. See static/js/sw.js.
    b'\n<script>if("serviceWorker" in navigator)'
    b'navigator.serviceWorker.register("/sw.js");</script>'
    # Save the field pages ahead of time. The worker only keeps what the phone has
    # actually loaded, so a page never opened online was a browser error page in
    # the field, and "remember to open every tab first" is not a plan (2026-09-18,
    # Lost Lands, no signal inside the venue). Any Hub page opened online loads
    # each _OFFLINE_WARM page once in a hidden frame; the frame runs the page for
    # real, so its scripts, styles and api calls all pass through the worker and
    # are kept, with no url list to fall out of step. `top===self` stops a warmed
    # page warming in turn, and the signed-out /login page skips it (every frame
    # would 302 back to login). Still network-first: nothing here is ever preferred
    # over a live answer.
    # ponytail: fixed page list, 30 min throttle per browser, fixed 90s frame life. Derive the list from
    # the upcoming trip if a second field page ever needs it.
    b'\n<script>if("serviceWorker" in navigator&&top===self&&location.pathname!="/login")'
    # 8s after load, not at it: React pages fetch their data after the load event,
    # and two hidden trips pages (~45 requests and map tiles) racing those fetches
    # slowed whichever page he had just opened (2026-10-13).
    b'addEventListener("load",function(){setTimeout(function(){'
    b'navigator.serviceWorker.ready.then(function(){var k="hub-warm-at",n=Date.now(),'
    b'l=' + json.dumps(_OFFLINE_WARM).encode() + b';'
    b'try{if(n-(+localStorage[k]||0)<18e5)return}catch(e){}'
    # The frames load side by side and stay for 90s. A frame closed 6s after its
    # load event passed on localhost and failed against the real PC from a hotel
    # link: the trip data and the map were still downloading and died with it.
    # Stamped only when the frames are taken down, so a Hub closed mid-warm tries
    # again on the next open rather than sitting out the throttle half-saved.
    b'var fs=l.map(function(u){var f=document.createElement("iframe");f.hidden=true;'
    b'f.src=u;document.body.appendChild(f);return f});'
    b'setTimeout(function(){fs.forEach(function(f){f.remove()});'
    b'try{localStorage[k]=n}catch(e){}},9e4)'
    b'})},8e3)});</script>'
)


@app.after_request
def _inject_app_icon_links(resp):
    """Add the home-screen icon + manifest links to every HTML page.

    The 24 template heads have no Jinja inheritance between them, so the
    alternative was 24 hand-edits and a 25th template that silently misses out.
    Injecting next to the `rel="icon"` link that every one of them already
    carries keeps it in one place and true for whatever gets added later.

    Registered AFTER _stamp_asset_versions, so it runs BEFORE it (Flask runs
    after_request in reverse) and the hrefs written here still get their `?v=`
    mtime stamp, and before _gzip_response so it is editing plain bytes.

    ponytail: regex on the one link tag every head has, not an HTML parser.
    Pages that already declare their own manifest (the trips templates, which
    need the guest-facing name) keep it and get only the worker scripts.
    """
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if ctype != "text/html" or resp.direct_passthrough:
        return resp
    body = resp.get_data()
    own = b'rel="manifest"' in body or b'rel="apple-touch-icon"' in body
    tags = _HEAD_SCRIPTS if own else _HEAD_TAGS + _HEAD_SCRIPTS
    body, n = _ICON_LINK.subn(lambda m: m.group(1) + tags, body, count=1)
    if n:
        resp.set_data(body)
    return resp


# Registered last of the HTML hooks, so it runs first, on plain bytes, before
# the version stamp hashes the body. See zoom_lock.py.
import zoom_lock  # noqa: E402
app.after_request(zoom_lock.lock_zoom)
import pull_refresh  # noqa: E402 — same plain-bytes slot as zoom_lock
app.after_request(pull_refresh.add_pull_refresh)
import marks.inject as marks_inject  # noqa: E402
app.after_request(marks_inject.add_marks_script)


@app.route("/jsx/<path:rel>")
def _jsx(rel):
    """Serve a .jsx file transpiled, so no page has to ship a compiler.

    URL is the file's path relative to hub/ — /jsx/static/js/App.jsx. Kept on its
    own prefix rather than overloading /static/ so there is no rule-precedence
    guessing between this and Flask's own static route.
    """
    src = (JSX_ROOT / rel).resolve()
    if src.suffix != ".jsx" or not src.is_file() or not src.is_relative_to(JSX_ROOT):
        abort(404)
    st = src.stat()
    resp = make_response(jsx_build.transpile(src))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    # Versioned like every other hub asset: a `?v=` that still matches the source
    # mtime cannot be stale, so serve it immutable and the browser stops re-asking
    # on every navigation — the home page loads ~10 of these, which over the tailnet
    # was ~10 revalidation round trips in front of every click. _stamp_asset_versions
    # rewrites the template's `?v=` to the live mtime, so an edit changes the URL and
    # shows on the next load; anything unversioned or mismatched still revalidates.
    want = request.args.get("v")
    if want and want == str(int(st.st_mtime)):
        resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "no-cache, max-age=0"
    resp.set_etag(f"{int(st.st_mtime)}-{st.st_size}")
    return resp.make_conditional(request)


import jsx_build  # noqa: E402 — hub/ is on sys.path from the block above
import public_area  # noqa: E402
public_area.register(app)
@app.after_request
def _conditional_json(resp):
    """Turn every JSON read on the Hub into a conditional GET.

    Hoisted out of forge/api.py 2026-08-19, where it was doing this for one module
    while every other module re-sent a byte-identical body on every load — the
    vault map alone is 452 KB gzipped that almost never changes between refreshes.
    Hashing the built body and answering 304 keeps the per-request read (so an edit
    still shows without a restart) and stops the transfer.

    Registered after the gzip hook on purpose: Flask runs after_request in reverse
    registration order, so this one runs FIRST — it hashes the uncompressed body,
    and a 304 short-circuits the compressor entirely.

    ponytail: md5 of the already-built body, not a per-module mtime scheme. The
    bodies hash in about a millisecond and content-hashing is right by construction.
    """
    if (request.method != "GET" or resp.status_code != 200
            or resp.is_streamed or "ETag" in resp.headers):
        return resp                      # send_file already carries its own ETag
    if resp.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
        return resp
    resp.set_etag(hashlib.md5(resp.get_data(), usedforsecurity=False).hexdigest())
    resp.headers.setdefault("Cache-Control", "no-cache")
    return resp.make_conditional(request)


from vault_path import vault_root  # noqa: E402 — needs the sys.path setup above

# Home-page data assembly, split out 2026-07-29. Imported here rather than higher up
# for the same reason: it imports gcal/cards/ynab, which need the sys.path setup above.
from home_data import (  # noqa: E402
    TRIPS_DB,
    _build_home_data,
    _shell_data,
)

JSX_ROOT = Path(__file__).resolve().parent
VAULT = vault_root()
PURCHASES_DB = VAULT / "data" / "purchases.db"
CHECKLISTS_DB = VAULT / "data" / "checklists.db"
JOBS_DB = VAULT / "data" / "jobs.db"
VAULT_MAP_DB = VAULT / "data" / "vault_map.db"
WORK_DB = (
    VAULT / "data" / "work.db"
)  # J&Co batch-prep + training; renamed from jc.db 2026-06-06
EARNINGS_DB = VAULT / "data" / "earnings.db"
OWED_DB = VAULT / "data" / "owed.db"  # what other people owe him; the /finances owed tab
STOCKS_DB = VAULT / "data" / "stocks.db"
CS2_DB = VAULT / "data" / "cs2.db"
FOOD_DB = VAULT / "data" / "food.db"
NEWS_DB = VAULT / "data" / "news.db"
NEWS_CACHE_DB = VAULT / "data" / "news-cache.db"
GLANCE_INDEX = VAULT / "data" / "job-glances-index.json"
GLANCE_DIR = VAULT / "wiki" / "notes" / "job-glances"
# Work-planner markdown paths live in tasks.py now (it owns the planner mirror).

PORT = 5002

# Exposure mode. Shares the trips app's env vars (dashboard/.env, loaded above):
# DASHBOARD_EXPOSED=1 turns on a password gate on every request via a /login
# session-cookie form, so one switch protects both apps. Default off, so home/tailnet use
# is never prompted. Unlike the trips app, Hub stays fully editable when exposed —
# the gate keeps strangers out while the authenticated user keeps full function on
# their own dashboard over untrusted wifi.
# See wiki/problems/dashboard-no-auth-on-public-funnel.
EXPOSED = os.environ.get("DASHBOARD_EXPOSED", "0") == "1"
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

# Signed session cookie for the password gate (see _require_password). The key is
# random and persisted via config.load_or_create_secret_key() — the same file the
# trips app uses — and is never derived from the password (see config.py for why).
# Only load-bearing when EXPOSED is on. Set DASHBOARD_SECRET_KEY to pin it.
app.secret_key = config.load_or_create_secret_key()
app.permanent_session_lifetime = timedelta(days=7)
# Surface the gate state to templates + the jobs blueprint so the sign-out
# control only renders when the password gate is actually on.
app.config["EXPOSED"] = EXPOSED

jobs_db.init(JOBS_DB)
app.register_blueprint(jobs_api.bp)


# the jobs dashboard moved back to /jobs (2026-09-28), reversing the 2026-07-29
# move to /apply. 308 keeps the method, so old bookmarks and any stale fetch() to
# /apply/api/... still work. the verbs have to be listed explicitly; flask's
# default is GET only, which 405s every stale write.
_LEGACY_VERBS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@app.route("/apply", methods=_LEGACY_VERBS)
@app.route("/apply/", defaults={"rest": ""}, methods=_LEGACY_VERBS)
@app.route("/apply/<path:rest>", methods=_LEGACY_VERBS)
def _apply_legacy_redirect(rest=""):
    qs = request.query_string.decode()
    # rest arrives decoded; re-quote so an encoded ? or % stays in the path
    return redirect("/jobs/" + quote(rest) + ("?" + qs if qs else ""), code=308)


vault_map_db.init(VAULT_MAP_DB)
app.register_blueprint(vault_map_api.bp)

capabilities_api.init(str(VAULT))
app.register_blueprint(capabilities_api.bp)

inventory_api.init(str(VAULT))
app.register_blueprint(inventory_api.bp)

# blueprints reads the shared CSS off disk relative to its own package — no init()
# and no DB. Registered here so /blueprints sits with the other read-only utilities.
app.register_blueprint(blueprints_api.bp)
app.register_blueprint(blueprints_api.legacy_bp)

# artifacts reads data/artifacts.json via vault_root() directly — no init() needed.
app.register_blueprint(artifacts_api.bp)
app.register_blueprint(viewer_api.bp)
# forge likewise reads data/forge-stats.json + data/forge-sets.json directly.
app.register_blueprint(forge_api.bp)

# workbench reads specs/plans live off disk and data/workbench.db directly
# (store.py resolves the vault itself via vault_path.vault_root()), so no init().
app.register_blueprint(workbench_api.bp)
app.register_blueprint(marks_api.bp)

barback_db.init(WORK_DB)
app.register_blueprint(barback_api.bp)

batch_prep_db.init(WORK_DB)
app.register_blueprint(batch_prep_api.bp)

# The juniper & co umbrella — one page, three tabs, both blueprints above as
# its payloads. Registered after them because its page pulls their static
# assets; /batch/ and /barback/ now 308 into it.
app.register_blueprint(jc_api.bp)

trips_db.init(TRIPS_DB)
app.register_blueprint(trips_api.bp)

food_db.init(FOOD_DB)
app.register_blueprint(food_api.bp)

# recipes reads recipes/*.md via vault_root() directly — no DB, so no init().
# Its one write surface is the shared grocery list in checklists.db, which
# checklists_db.init() above already prepared.
app.register_blueprint(recipes_api.bp)

purchases_db.init(PURCHASES_DB)
app.register_blueprint(purchases_api.bp)

checklists_db.init(CHECKLISTS_DB)
app.register_blueprint(checklists_api.bp)

app.register_blueprint(work_api.bp)

finances_db.init(EARNINGS_DB)
finances_owed.init(OWED_DB, TRIPS_DB)
app.register_blueprint(finances_api.bp)

stocks_db.init(STOCKS_DB)
app.register_blueprint(stocks_api.bp)

try:
    news_db.init(NEWS_DB, NEWS_CACHE_DB)
except Exception:
    app.logger.exception("news_db.init failed; Hub starting without the news module")
# INSERT OR IGNORE against the seed + the tracked-tickers list -- a later edit
# of either row (his own, or the /stock watchlist) always wins; see db.py's
# seed_sources/seed_ticker_topics docstrings. Each guarded on its own: a bad
# seed file or an unmigrated/missing stocks.db must log and move on, never
# take the whole Hub process down at import time over one module's seed step.
try:
    news_db.seed_sources(JSX_ROOT / "news" / "sources_seed.json")
except Exception:
    app.logger.exception("news_db.seed_sources failed; Hub starting without a fresh source seed")
try:
    news_db.seed_ticker_topics(STOCKS_DB)
except Exception:
    app.logger.exception("news_db.seed_ticker_topics failed; Hub starting without ticker topics")
app.register_blueprint(news_api.bp)
app.register_blueprint(automations_api.bp)
app.register_blueprint(mail_api.bp)

# Float & Ledger — a project on the /artifacts catalog like /forge, deliberately
# NOT a hub_modules.py launcher tile (see ledger/CLAUDE.md).
ledger_db.init(CS2_DB)
app.register_blueprint(ledger_api.bp)


@app.before_request
def _require_password():
    # When DASHBOARD_EXPOSED=1, every request (including the jobs blueprint) needs
    # a valid session, established by the password-only /login form (no username —
    # the server never used one). Off by default, so home use is never prompted.
    # The login page, public/ and the exact shared files it loads stay reachable so
    # the form can render; the rest of /static/ is signed-in only (public_area.py).
    if not EXPOSED:
        return None
    p = request.path
    # /sw.js too: _HEAD_SCRIPTS registers it on every page, login included, and
    # _HEAD_TAGS links the manifest there.
    if (p in ("/login", "/sw.js", "/static/assets/manifest.webmanifest")
            or p.startswith("/public/") or p in public_area.PUBLIC_EXACT):
        return None
    if session.get("authed"):
        return None
    # Unauthenticated. Send browsers to the login form; answer API/XHR callers
    # with a 401 so they don't try to parse an HTML redirect.
    if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
        return redirect(url_for("login"))
    return Response("Authentication required.", 401)


@app.route("/login", methods=["GET", "POST"])
def login():
    # Password-only gate. On success, set a 7-day signed session cookie. Fails
    # closed: a wrong password or an empty PASSWORD both keep the user out.
    if not EXPOSED:
        return redirect("/")
    error = None
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if PASSWORD and hmac.compare_digest(supplied, PASSWORD):
            session.permanent = True
            session["authed"] = True
            return redirect("/")
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    # Clears the signed session cookie set by /login. POST-only so a stray
    # link prefetch can't sign you out. Bounces to the login form when the gate
    # is on, else home (logout is a no-op for un-gated home use).
    session.clear()
    return redirect(url_for("login") if EXPOSED else "/")


from hub_modules import MODULES as _MODULES


@app.route("/hub-modules.js")
def hub_modules_js():
    """Serve the canonical module list as window.MODULES so every page (static or
    jinja) reads one source, plus window.__HUB_EXPOSED__ for the top bar's
    sign-out button."""
    # Signed out on an exposed Hub (the login page) the bar gets no module list.
    signed_out = EXPOSED and not session.get("authed")
    resp = make_response("window.MODULES=" + json.dumps([] if signed_out else _MODULES)
                         + ";window.__HUB_EXPOSED__=" + json.dumps(EXPOSED) + ";")
    resp.headers["Content-Type"] = "application/javascript"
    if signed_out:
        # Same URL as the signed-in list, so never let a browser keep this one.
        resp.headers["Cache-Control"] = "no-store"
        return resp
    # Every page loads this, so no-store cost a round trip on every navigation.
    # _stamp_asset_versions puts a hash of the list in the URL, so a matching
    # `?v=` is provably current and the browser can keep it; anything else still
    # comes back fresh, and a changed list changes the URL on the next render.
    if request.args.get("v") == _asset_token("/hub-modules.js"):
        resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/favicon.ico")
def favicon():
    # Every template names the icon explicitly, so this only catches the clients
    # that ask for /favicon.ico anyway regardless of the tag — crawlers, and the
    # browser on any error page rendered outside a template.
    return redirect("/static/assets/favicon.png", code=301)


@app.route("/sw.js")
def service_worker():
    """Hand out the offline worker from the root.

    A worker only controls the paths under the URL it was served from, so one at
    /static/js/sw.js could cache assets and nothing else — the pages themselves,
    and /api/home, would still fail offline. The file lives with the rest of the
    JS and is served here to claim the whole origin.

    no-store because this is the one file a stale copy would pin every other file
    behind: the browser would keep running an old worker's caching rules forever.
    """
    resp = make_response((_HUB_DIR / "static" / "js" / "sw.js").read_text())
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    return resp


@app.route("/")
def home():
    # Serve the shell with no network calls so first paint is immediate; the panels
    # hydrate from /api/home client-side. never serve a stale home document —
    # versioned assets handle css/jsx, but the HTML itself must always re-fetch so
    # chrome changes land on a plain reload.
    resp = make_response(
        render_template("index.html", data=_shell_data(), exposed=EXPOSED)
    )
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    return resp


@app.route("/api/home")
def api_home():
    return jsonify(_build_home_data())


@app.route("/api/transit")
def api_transit():
    # ?dest=<calendar location>&dest=... — today's destinations, free text, as
    # the client already holds them. Geocoded + cached server-side (see transit.py).
    # `line` arrives on the card's SECOND call, once the router has said which
    # trains it actually put him on — those get watched end to end. The first call
    # has none and falls back to the nearest-station scope, so the card is never
    # blank waiting for a route.
    return jsonify(transit.view(request.args.getlist("dest"), request.args.getlist("line"),
                                request.args.get("day", "")))


@app.route("/api/transit/routes")
def api_transit_routes():
    # ?from=lat,lng&to=lat,lng&time=<event start, naive local>. Google's transit
    # routes (transit.google_routes); {"itineraries": null} tells the card to fall
    # back to the self-hosted router.
    return jsonify({"itineraries": transit.google_routes(
        request.args.get("from", ""), request.args.get("to", ""), request.args.get("time", ""))})


@app.route("/api/wx-extras")
def api_wx_extras():
    return jsonify({"pollen": wx_extras.pollen()})


@app.route("/api/calendar/calendars")
def api_calendar_list():
    if not gcal.is_authenticated():
        return jsonify({"error": "not authenticated"}), 401
    service = gcal._get_service()
    items = service.calendarList().list().execute().get("items", [])
    writable = [
        {"id": c["id"], "summary": c.get("summary", c["id"])}
        for c in items
        if c.get("accessRole") in ("owner", "writer")
        and not any(k in c["id"] for k in ["holiday", "@import.calendar.google.com"])
    ]
    return jsonify(writable)


@app.route("/api/calendar/events", methods=["POST"])
def api_create_event():
    if not gcal.is_authenticated():
        return jsonify({"error": "not authenticated"}), 401
    data = request.get_json()
    calendar_id = data.get("calendar_id", "primary")
    event_body = data.get("event", {})
    if not event_body.get("summary"):
        return jsonify({"error": "title required"}), 400
    gcal.snap_event_body(event_body)  # 5-min grid for human-created events
    result = gcal.create_event(event_body, calendar_id)
    return jsonify({"id": result["id"]}), 201


@app.route("/api/calendar/events/<event_id>", methods=["PUT", "DELETE"])
def api_update_or_delete_event(event_id):
    if not gcal.is_authenticated():
        return jsonify({"error": "not authenticated"}), 401
    if request.method == "DELETE":
        ok = gcal.delete_event(event_id)
        return jsonify({"ok": ok}), (200 if ok else 500)
    data = request.get_json()
    calendar_id = data.get("calendar_id", "primary")
    event_body = data.get("event", {})
    # patch, not update: a full update_event PUT would drop any field the editor
    # didn't send — notably colorId, which would strip the event's Tomato (task)
    # marker and unlink it from its task row. patch only touches the sent fields.
    gcal.snap_event_body(event_body)  # 5-min grid for schedule-editor drags/edits
    result = gcal.patch_event(event_id, event_body, calendar_id)
    return jsonify({"id": result["id"]})


@app.route("/api/gmail/message/<message_id>")
def api_gmail_message(message_id):
    if not gmail.is_authenticated():
        return jsonify({"error": "not authenticated"}), 401
    return jsonify(gmail.fetch_message_body(message_id))


# ── Google OAuth sign-in flows ──────────────────────────────────────────────────
# Ported from the legacy port-5001 app (dashboard/api.py) when Hub became home
# base. Token files are shared between both ports, so re-authing here updates the
# same tokens the rest of the vault uses. Always run these on http://localhost:5002
# (Google gives localhost special treatment; the tailnet host is not registered).


@app.route("/api/calendar/auth")
def api_calendar_auth():
    if not gcal.has_credentials():
        return (
            "<h2>Google Calendar Setup</h2>"
            "<p>Put <code>credentials.json</code> (from Google Cloud Console) "
            "in the <code>dashboard/</code> folder, then revisit this page.</p>"
            "<p>Steps: console.cloud.google.com → Enable Calendar API → "
            "Credentials → Create OAuth 2.0 Client ID (Web app) → "
            "add <code>http://localhost:5002/api/calendar/callback</code> as redirect URI → "
            "Download JSON → rename to credentials.json</p>",
            400,
        )
    redirect_uri = request.url_root.rstrip("/") + "/api/calendar/callback"
    return redirect(gcal.get_auth_url(redirect_uri))


@app.route("/api/calendar/callback")
def api_calendar_callback():
    ok, err = gcal.handle_callback(request.url)
    if ok:
        gcal.fetch_events()
        return redirect("/")
    return f"Authentication failed: {err}", 400


@app.route("/api/gmail/auth")
def api_gmail_auth():
    if not gmail.has_credentials():
        return (
            "<h2>Gmail Setup</h2>"
            "<p>Put <code>credentials.json</code> (from Google Cloud Console) "
            "in the <code>dashboard/</code> folder, then revisit this page.</p>"
            "<p>Steps: console.cloud.google.com → Enable Gmail API → "
            "Credentials → OAuth 2.0 Client ID (Web app) → "
            "add <code>http://localhost:5002/api/gmail/callback</code> as redirect URI → "
            "Download JSON → rename to credentials.json</p>",
            400,
        )
    redirect_uri = request.url_root.rstrip("/") + "/api/gmail/callback"
    return redirect(gmail.get_auth_url(redirect_uri))


@app.route("/api/gmail/callback")
def api_gmail_callback():
    ok, err = gmail.handle_callback(request.url)
    if ok:
        return redirect("/")
    return f"Gmail authentication failed: {err}", 400


@app.route("/api/drive/status")
def api_drive_status():
    return jsonify(
        {
            "has_credentials": gdrive.has_credentials(),
            "is_authenticated": gdrive.is_authenticated(),
            "needs_reauth": gdrive.needs_reauth(),
        }
    )


@app.route("/api/drive/auth")
def api_drive_auth():
    if not gdrive.has_credentials():
        return (
            "<h2>Google Drive Setup</h2>"
            "<p>Put <code>credentials.json</code> in <code>dashboard/</code>, then revisit.</p>"
            "<p>Enable the Google Drive API in your Google Cloud project and add "
            "<code>http://localhost:5002/api/drive/callback</code> as a redirect URI.</p>",
            400,
        )
    redirect_uri = request.url_root.rstrip("/") + "/api/drive/callback"
    return redirect(gdrive.get_auth_url(redirect_uri))


@app.route("/api/drive/callback")
def api_drive_callback():
    ok, err = gdrive.handle_callback(request.url)
    if ok:
        return redirect("/")
    return f"Google Drive authentication failed: {err}", 400


@app.route("/api/docs/status")
def api_docs_status():
    return jsonify(
        {
            "has_credentials": gdocs.has_credentials(),
            "is_authenticated": gdocs.is_authenticated(),
            "needs_reauth": gdocs.needs_reauth(),
        }
    )


@app.route("/api/docs/auth")
def api_docs_auth():
    if not gdocs.has_credentials():
        return (
            "<h2>Google Docs Setup</h2>"
            "<p>Put <code>credentials.json</code> in <code>dashboard/</code>, then revisit.</p>"
            "<p>Enable the Google Docs API in your Google Cloud project and add "
            "<code>http://localhost:5002/api/docs/callback</code> as a redirect URI.</p>",
            400,
        )
    redirect_uri = request.url_root.rstrip("/") + "/api/docs/callback"
    return redirect(gdocs.get_auth_url(redirect_uri))


@app.route("/api/docs/callback")
def api_docs_callback():
    ok, err = gdocs.handle_callback(request.url)
    if ok:
        return redirect("/")
    return f"Google Docs authentication failed: {err}", 400


@app.route("/api/sheets/status")
def api_sheets_status():
    return jsonify(
        {
            "has_credentials": gsheets.has_credentials(),
            "is_authenticated": gsheets.is_authenticated(),
            "needs_reauth": gsheets.needs_reauth(),
        }
    )


@app.route("/api/sheets/auth")
def api_sheets_auth():
    if not gsheets.has_credentials():
        return (
            "<h2>Google Sheets Setup</h2>"
            "<p>Put <code>credentials.json</code> in <code>dashboard/</code>, then revisit.</p>"
            "<p>Enable the Google Sheets API in your Google Cloud project and add "
            "<code>http://localhost:5002/api/sheets/callback</code> as a redirect URI.</p>",
            400,
        )
    redirect_uri = request.url_root.rstrip("/") + "/api/sheets/callback"
    return redirect(gsheets.get_auth_url(redirect_uri))


@app.route("/api/sheets/callback")
def api_sheets_callback():
    ok, err = gsheets.handle_callback(request.url)
    if ok:
        return redirect("/")
    return f"Google Sheets authentication failed: {err}", 400


def _glance_body_lines(lines: list[str]) -> list[str]:
    """Lines after the frontmatter block (if any)."""
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    return lines[start:]


def _glance_field(body: str, name: str) -> str:
    m = re.search(rf"\*\*{re.escape(name)}:\*\*\s*(.+)", body)
    return m.group(1).strip() if m else ""


def _glance_section_bullets(body_lines: list[str], section_name: str) -> list[str]:
    result = []
    in_section = False
    for line in body_lines:
        if f"**{section_name}:**" in line:
            in_section = True
            continue
        if in_section:
            if re.match(r"\*\*.+:\*\*", line.strip()):
                break
            stripped = line.strip().lstrip("-").strip()
            if stripped:
                result.append(stripped)
    return result


def _glance_links(body_lines: list[str]) -> list[dict]:
    links = []
    in_links = False
    for line in body_lines:
        if "**Links:**" in line:
            in_links = True
            continue
        if in_links:
            if re.match(r"\*\*.+:\*\*", line.strip()):
                break
            m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
            if m:
                links.append({"label": m.group(1), "url": m.group(2)})
    return links


def _parse_glance(text: str) -> dict:
    """Parse a job-glance markdown file into structured dashboard data."""

    body_lines = _glance_body_lines(text.splitlines())
    body = "\n".join(body_lines)

    reply_raw = _glance_field(body, "Reply needed").lower()
    return {
        "tldr": _glance_field(body, "TL;DR"),
        "role": _glance_field(body, "Role"),
        "applied": _glance_field(body, "Applied"),
        "last_activity": _glance_field(body, "Last activity"),
        "reply_needed": reply_raw in ("yes", "true", "1"),
        "points": _glance_section_bullets(body_lines, "Key points"),
        "links": _glance_links(body_lines),
    }


@app.route("/api/gmail/message/<message_id>/summarize")
def api_gmail_summarize(message_id):
    if not GLANCE_INDEX.exists():
        return jsonify({"error": "no glance available — run /gmail to generate"}), 404
    try:
        index = json.loads(GLANCE_INDEX.read_text(encoding="utf-8"))
    except Exception:
        app.logger.exception("glance index unreadable: %s", GLANCE_INDEX)
        return jsonify({"error": "glance index unreadable"}), 500
    glance_slug = index.get(message_id)
    if not glance_slug:
        return jsonify({"error": "no glance available for this message"}), 404
    glance_path = GLANCE_DIR / f"{glance_slug}.md"
    if not glance_path.exists():
        return jsonify(
            {"error": "glance file not found — may have been removed after closure"}
        ), 404
    try:
        return jsonify(_parse_glance(glance_path.read_text(encoding="utf-8")))
    except Exception as exc:
        return jsonify({"error": f"glance parse error: {exc}"}), 500


@app.route("/api/tasks/complete", methods=["POST"])
def api_task_complete():
    task_id = (request.get_json() or {}).get("id", "")
    if not tasks.complete(task_id):
        return jsonify({"error": "task not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/tasks/reopen", methods=["POST"])
def api_task_reopen():
    task_id = (request.get_json() or {}).get("id", "")
    if not tasks.reopen(task_id):
        return jsonify({"error": "task not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/tasks/delete", methods=["POST"])
def api_task_delete():
    # `source` ("active"/"completed") is accepted for frontend compatibility but
    # ignored — delete resolves by task_key regardless of which list it's in.
    task_id = (request.get_json() or {}).get("id", "")
    if not tasks.delete(task_id):
        return jsonify({"error": "task not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/tasks/add", methods=["POST"])
def api_task_add():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    section = (data.get("section") or "general").lower()
    if not name:
        return jsonify({"error": "name required"}), 400
    task = tasks.add(
        name,
        section=section,
        group_label=data.get("group_label"),
        urgency=data.get("urgency"),
        input_level=data.get("input_level"),
    )
    return jsonify({"ok": True, "task": task})


@app.route("/api/tasks/update", methods=["POST"])
def api_task_update():
    data = request.get_json() or {}
    task_id = data.get("id", "")
    # Empty name -> None so we don't blank the title; description "" clears it.
    name = (data.get("name") or "").strip() or None
    # group_label / urgency / input_level: pass through only when the key is
    # present, so an absent key leaves the field untouched while an empty string
    # clears it.
    extra = {}
    for field in ("group_label", "urgency", "input_level"):
        if field in data:
            extra[field] = data.get(field) or ""
    if not tasks.update(
        task_id, name=name, description=data.get("description"), **extra
    ):
        return jsonify({"error": "task not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/briefing/snapshot", methods=["POST"])
def api_briefing_snapshot():
    # The browser posts today's computed briefing bits (forecast + the merged
    # bring/prep lists). We key on the SERVER's local day, never the client's, so
    # a stale tab can't rewrite a past (frozen) day. Idempotent upsert.
    data = request.get_json() or {}
    written = briefing_snapshot.save_today(
        data.get("forecast"), data.get("bring"), data.get("prep")
    )
    return jsonify({"ok": True, "date": written})


@app.route("/api/scheduler/status")
def api_scheduler_status():
    cfg = skill_scheduler.load_config()
    return jsonify(
        {
            "active_machine": cfg.get("active_machine"),
            "this_machine": socket.gethostname(),
            "is_active": skill_scheduler.is_active_machine(cfg),
            "jobs": cfg.get("jobs", []),
            "recent_runs": skill_scheduler.recent_runs(limit=20),
        }
    )


def _inventory_scan_loop():
    """Daily scan of this computer's programs. A missing or failing scanner is logged, never fatal."""
    import subprocess
    import time

    time.sleep(60)
    while True:
        try:
            r = subprocess.run([str(inventory_api.SCAN_BIN)], capture_output=True, text=True, timeout=3600)
            if r.returncode:
                app.logger.error("inventory-scan exited %s: %s", r.returncode, (r.stderr or "")[-500:])
        except Exception:
            app.logger.exception("inventory-scan could not run")
        time.sleep(24 * 3600)


if os.environ.get("DEMO_MODE") == "1":
    demo_mode.finish(app)


if __name__ == "__main__":
    print(f"hub dashboard: http://0.0.0.0:{PORT}")
    # Start the headless skill scheduler only in the serving process (not on
    # import, so tests don't spawn the thread). With an empty config / no
    # active_machine it fires nothing.
    skill_scheduler.SkillScheduler().start()
    # Same guard, same reason: the submit worker drains `approved` rows one at
    # a time with a random 30-90s gap. start_worker() is idempotent, so this
    # is safe even if something else in-process calls it too.
    jobs_submitter.start_worker()
    threading.Thread(target=_inventory_scan_loop, daemon=True, name="inventory-scan").start()
    if EXPOSED:
        if not PASSWORD:
            raise SystemExit(
                "Refusing to start: DASHBOARD_EXPOSED=1 but DASHBOARD_PASSWORD is empty. "
                "Set a password in dashboard/.env, or unset DASHBOARD_EXPOSED for home use."
            )
        print(
            "Exposed mode ON — password required on every request (Hub stays editable for the authenticated user)."
        )
    # threaded=True so concurrent requests don't queue behind one another (the home
    # route blocks on external API calls; a single worker would serialize page loads).
    jsx_build.warm()
    mail_api.warm()
    news_api.warm()
    # Two things made every page load from Windows pay ~200ms PER REQUEST, measured
    # 2026-09-04 with curl.exe against this port: (1) Windows resolves `localhost`
    # to ::1 first and the server only listened on IPv4, so each new connection
    # sat in the IPv6 attempt before falling back; (2) the dev server answered
    # every response with `Connection: close`, so all ~20 requests a page makes
    # opened a new connection and paid that wait again. HTTP/1.1 turns on
    # keep-alive, and a second listener on ::1 answers the IPv6 attempt at once.
    # The IPv6 socket is V6ONLY so it can share the port with the IPv4 one, and
    # the IPv4 one stays because WSL's relay hangs 127.0.0.1 when only :: listens.
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    v6.bind(("::", PORT))
    v6.listen(128)
    threading.Thread(
        target=make_server("::", PORT, app, threaded=True, fd=v6.fileno()).serve_forever,
        daemon=True,
    ).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)  # noqa: S104 -- LAN/Tailscale-only dashboard, intended reachable from every interface
