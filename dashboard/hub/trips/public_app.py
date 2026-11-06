"""The public trips mirror — the real trips UI, read-only, on its own port.

This is NOT a copy of the trips dashboard. It is the same dashboard, run by a
second process. It imports the same blueprint, serves the same trips.js and
trips.css off disk, and reads the same data/trips.db. Change the trips board in
Hub and this surface serves the changed file on its next page load, because
there is only one set of files. Nothing is ever copied across, so nothing can
drift.

The only differences are which blueprints get registered and one config flag:

  * Hub registers fifteen blueprints. This registers trips, and nothing else.
    Jobs, purchases, finances, stocks and work are not merely hidden here —
    they do not exist in this process, so no URL can reach them. That is what
    makes the port safe to hand to Tailscale Funnel, which exposes an entire
    port and cannot expose a fraction of one.
  * GUEST=True, which the shared templates read to put `class="guest"` on the
    body. One CSS block in trips.css then hides the controls. Hub never sets
    the flag, so Hub renders exactly as before.

Read-only is enforced here rather than in the CSS, because hiding a button is a
cosmetic act and anyone can still send the request by hand. `_read_only_gate`
rejects every method that is not a GET, for every route, so a control that the
CSS misses still cannot change anything.

Three more things this process does that Hub does not, added 2026-08-20:

  * It serves an ALLOWLIST of static files, not a folder. `static_folder` points
    at Hub's own static directory, so "serve the folder" meant serving
    /static/mockups/vault_map_data.json — 2.6 MB indexing all 7,182 paths in the
    private vault — to anyone with the URL and no passcode at all. See
    _STATIC_ALLOW. Anything new in Hub's static dir is unreachable here until
    someone names it.
  * It caps wrong codes GLOBALLY, not only per caller. The per-IP counter keys on
    a header the caller controls, so on its own it could be walked around a
    10,000-entry code space. See _ALL_FAILS.
  * It sets a content security policy and the rest of the hardening headers on
    every response. See _CSP and `_harden`.

The bind stays on 0.0.0.0 deliberately. Under WSL2 the Windows-side relay dials
the VM, so a loopback bind breaks the funnel; and it costs nothing, because that
relay listens on Windows 127.0.0.1 only and the VM sits behind a NAT'd vEthernet
(192.168.64.0/20) the house LAN cannot route to.

This file is the facade over the split (Task 6 of the 2026-09-24 trips-split
plan): it owns every module-level constant and global, and `create_app()`.
Route handlers and hooks live in `public_gate.py` (the keypad, the completion
wall, rate limits) and `public_lostlands.py` (the open festival link), each
reached through the `_pa` alias at call time so a monkeypatch here (`vault_root`,
`_LL_TRIP_ID`, `_FAILS`) still lands. See dashboard/hub/tests/test_trips_facades.py.

Usage:
    python3 public_app.py [--port 5003]
"""

from __future__ import annotations

import hmac  # noqa: F401 -- unused here; kept so it resolves on the frozen manifest (Rule 4)
import json  # noqa: F401 -- unused here; kept so it resolves on the frozen manifest (Rule 4)
import logging
import os
import re
import sys
import time  # noqa: F401 -- unused here; kept so it resolves on the frozen manifest (Rule 4)
from datetime import timedelta
from pathlib import Path

_HUB_DIR = Path(__file__).resolve().parent.parent
_DASHBOARD = _HUB_DIR.parent
_TRIPS_DIR = Path(__file__).resolve().parent
for _p in (str(_DASHBOARD), str(_HUB_DIR)):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path[:0] = [str(_HUB_DIR), str(_DASHBOARD)]

if __name__ == "__main__":
    # trips-public.service runs this file as a script (ExecStart=python3
    # public_app.py). Hand off to the package module instead: the section files
    # import `trips.public_app`, so running the body here as `__main__` would
    # give them a second, divergent copy (and the relative imports below fail).
    from trips import public_app as _pkg  # noqa: E402

    _pkg.serve(int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else _pkg.DEFAULT_PORT)
    raise SystemExit(0)

# jsonify, make_response, redirect, render_template, request, session: only
# `Flask` is used directly below now (the rest moved with the routes that used
# them), but all are on the pre-split manifest, so they stay imported -- Rule 4.
from flask import (  # noqa: E402,F401
    Flask, jsonify, make_response, redirect, render_template, request, session,
)
import config  # noqa: E402
import public_area  # noqa: E402
import sqlite_helpers  # noqa: E402,F401 -- unused here; kept for the frozen manifest (Rule 4)
import zoom_lock  # noqa: E402
from vault_path import vault_root  # noqa: E402

from trips import api as trips_api  # noqa: E402
from trips import db as trips_db  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5003

# Hub's own routes that the shared trips templates reference. Everything else on
# Hub — every module blueprint — is deliberately absent from this process.
_SHARED_STATIC = _HUB_DIR / "static"

# Reachable on Hub, withheld here.
#   /trips/log        — the post-trip review is Sam's decision log of what he
#                       attended and what he passed on, his own bookkeeping.
#   /trips/api/guest-codes
#                     — the gate's own admin surface. Its writes are already dead
#                       here (non-GET is rejected), but the GET would hand every
#                       guest's name and passcode to the internet.
#   /trips/api/trips/roster
#                     — everyone who has ever been on any trip. It backs the "add
#                       from roster" picker, an edit affordance a guest has no use
#                       for, and it is a cross-trip leak of exactly the kind the
#                       scoping below exists to prevent.
#   /trips/api/share-url
#                     — shells out to tailscale on every call. It only returns the
#                       URL the guest already typed, so it leaks nothing, but a
#                       public endpoint that spawns a process per request is a
#                       free DoS lever.
_WITHHELD_PREFIXES = (
    #   /trips/preview    — Hub's "view as", which re-scopes the session onto a
    #                       given member. Harmless on the private port, where the
    #                       only caller is Sam; mounted here it would be a GET
    #                       that walks an unlocked guest onto someone else's
    #                       trips, which is the one thing the gate exists to stop.
    "/trips/preview",
    #   /trips/crew       — the crew page: every guest's name, passcode, phone,
    #                       email and address, and the approve buttons.
    "/trips/crew",
    #   /trips/api/packing — Sam's own packing lists. Personal, not the trip's.
    "/trips/api/packing",
    "/trips/log",
    "/trips/api/guest-codes",
    "/trips/api/trips/roster",
    "/trips/api/share-url",
    #   /trips/api/gate-freeze
    #                     — the reset for the strike system. A POST is already dead
    #                       here, but a public route that reopens the keypad is the
    #                       one thing a guesser would want most.
    "/trips/api/gate-freeze",
    #   /trips/api/prefs/sync, /trips/api/prefs/unmatched
    #                     — the sync spends Sam's Google quota and the
    #                       unmatched list is every submission nobody could be
    #                       identified from, which is his to resolve. No guest
    #                       path reaches either: the two forms are answered on
    #                       this page now, and the Google originals are a legacy
    #                       source Sam pulls from Hub when he wants to.
    "/trips/api/prefs/sync",
    "/trips/api/prefs/unmatched",
    #   /trips/api/intakes — Sam's approval queue: every guest's pending
    #                     submission across every trip, plus approve and reject.
    "/trips/api/intakes",
)

# The only paths that may be written to. A literal allowlist, not a prefix:
# "/gate" as a prefix would silently make any future /gate/* route writable.
#
# /trips/api/prefs/submit is the one write a GUEST performs. It is safe to open
# here because the route does not take a subject: api._submit_ref reads the
# member key off this process's own guest_codes row, so the only row a guest can
# write is their own no matter what they post. See api.api_submit_prefs.
# /trips/api/prefs/card is the second guest write, and it is safe for exactly the
# same reason: api_pref_card runs _submit_ref, which on this process reads the
# member key off the guest_codes row and never off the body. A guest posting Leo's
# key restyles their OWN card. It was missing from this list until 2026-08-28,
# which meant the card designer loaded on the mirror, rendered every swatch, and
# 405'd on the pick — the one control a guest is given, dead in the one place it
# was for.
# The intake POST is the third guest write, matched as a pattern because the trip
# id is in the path. It only inserts a pending row for the caller's own key (read
# off the guest_codes row, never the body) on a trip _gate already scoped to them,
# so nothing is applied until Sam approves. Anchored: no other path matches.
_INTAKE_POST = re.compile(r"^/trips/api/trips/\d+/intake$")
# A whole-trip form is bigger than the 4 KB every other mirror body is capped at.
_INTAKE_MAX_BYTES = 65536
_WRITABLE_PATHS = (
    "/gate", "/gate/request", "/gate/me", "/trips/api/prefs/submit",
    "/trips/api/prefs/card",
)

# `static_folder` below is Hub's OWN static directory — the same one the private
# dashboard serves. Handing the whole folder to the funnel is what let
# /static/mockups/vault_map_data.json (2.6 MB indexing all 7,182 paths in the
# vault: contacts, problems, finance, hooks) and Hub's module source
# (CreditCards.jsx, Subscriptions.jsx, Tasks.jsx, today.jsx) be fetched with no
# passcode at all. So this process serves an allowlist instead: exactly what
# gate.html, trips-landing.html and trips.html reference, nothing else.
#
# An allowlist, not a denylist, because the leak was a file nobody thought about.
# Anything new that lands in Hub's static folder is unreachable here by default,
# which is the only version of this rule that stays true without being remembered.
_STATIC_ALLOW = frozenset({
    "css/base.css",
    # the head script that starts a page's data requests during parse (added
    # 2026-10-22); listed because public_area.SHARED_STATIC names it
    "js/early-fetch.js",
    # the shared component layer, linked right after base.css in every page that
    # carries one. added 2026-09-16 when the first promotions landed: without it a
    # guest's board 404s on every button and dialog part the Hub has promoted.
    "css/components.css",
    # the tabbed 3-pane origin, the board's page chassis, linked right after
    # components.css. added 2026-09-23 when the chassis left trips.css for it.
    "css/origins/tabbed-3-pane.css",
    "css/themes/cobalt.css",
    "css/themes/liquid.css",
    # liquid.css draws the brand mark from this file (added 2026-10-10 with the theme)
    "assets/brand-mark.svg",
    "assets/brand-mark-liquid.svg",
    "css/map.css",
    # The food tab is the /food area renderer mounted into the trips shell. Both files
    # are the same ones Hub serves — that shared copy is the point, and it is what
    # keeps the guest's board and Hub's board from drifting. Neither one reaches the
    # database: the data still comes from the trip-scoped endpoints in trips/api.py.
    "css/food-view.css",
    "js/basemap.js",
    "js/food-view.js",
    "js/theme-switch.js",
    # theme-switch.js injects both on every page (liquid scroll bar); missing
    # here, every guest page 404'd on the script (2026-11-03)
    "css/liquid-scrollbar.css",
    "js/liquid-scrollbar.js",
    # the shared top bar is React (topbar.jsx, served by its own route below)
    "vendor/react.production.min.js",
    "vendor/react-dom.production.min.js",
    "assets/favicon.png",
    # Add to Home Screen. apple-touch-icon is the one Safari actually reads; the
    # maskable pair is what keeps Android's launcher mask from cropping the
    # bracket corners, which sit 53% out from centre at full bleed.
    "assets/apple-touch-icon.png",
    "assets/icon-192.png",
    "assets/icon-512.png",
    "assets/icon-maskable-192.png",
    "assets/icon-maskable-512.png",
    "assets/manifest-trips.webmanifest",
    "assets/mark-dark.svg",
    "assets/mark-light.svg",
})
# Two vendored directories go in whole rather than file by file. leaflet.css
# names its marker images by relative path; the webfonts are a dozen woff2 files
# under content-hashed names that change whenever tools/vendor-fonts.py re-runs,
# and an allowlist nobody remembers to update is how the pages here silently lose
# their typeface. Both are third-party binaries holding nothing of Sam's.
_STATIC_ALLOW_DIRS = ("vendor/leaflet/", "vendor/fonts/")

# Reachable before unlocking. Everything else redirects to the keypad, including
# /trips/static/. /hub-modules.js and topbar.jsx are open (public_area.PUBLIC_EXACT)
# because the keypad draws the top bar; the mirror's module list is always [].
# Single files match exactly (public_area.PUBLIC_EXACT): as prefixes, /static/vendor/fonts/fonts.css also let
# fonts.css.header through, since vendor/fonts/ is an allowed folder.
_PUBLIC_PREFIXES = ("/gate", "/robots.txt", "/lostlands/", "/public/")
# Every shared file must pass _static_allowlist, or a signed-out page 404s on it.
assert all(p in _STATIC_ALLOW or p.startswith(_STATIC_ALLOW_DIRS) for p in public_area.SHARED_STATIC), \
    sorted(p for p in public_area.SHARED_STATIC if p not in _STATIC_ALLOW and not p.startswith(_STATIC_ALLOW_DIRS))

# ── The open Lost Lands link ───────────────────────────────────────────────
# /lostlands/<key>/ is the festival page with nothing to type (2026-09-18: the
# crew is inside a venue with no signal, and a keypad plus two forms is not a
# thing to walk someone through in a field). "/lostlands/" is public above, so
# the KEY is the whole gate: every route under it 404s on a wrong one.
#
# It is deliberately NOT /trips/59 with the gate lifted. That board's data call
# ships full rows: the crew's emails and home addresses, the hotel confirmation
# and wifi password, flight confirmation numbers. This page gets _ll_slim_trip()
# and nothing else, and its files come from the fixed table below, so a key
# holder can reach exactly one page and the five files it loads.
# The routes and _ll_slim_trip/_ll_ok live in public_lostlands.py; this facade
# just owns the three constants they read.
_LL_TRIP_ID = 59
_LL_KEY = "31538eac273c"
_LL_FILES = {   # name under /lostlands/<key>/f/  ->  (path, content type)
    "hallmark.js": (_TRIPS_DIR / "frontend" / "hallmark" / "lostlands.js", "application/javascript; charset=utf-8"),
    "hallmark.css": (_TRIPS_DIR / "frontend" / "hallmark" / "lostlands.css", "text/css; charset=utf-8"),
    "trips.css": (_TRIPS_DIR / "frontend" / "static" / "trips.css", "text/css; charset=utf-8"),
    "components.css": (_HUB_DIR / "static" / "css" / "components.css", "text/css; charset=utf-8"),
    "lostlands-map-2026.webp": (_TRIPS_DIR / "frontend" / "static" / "lostlands-map-2026.webp", "image/webp"),
}

# Reachable by an unlocked guest who has not finished the forms. Everything else
# waits behind the wall.
# The form itself has to be reachable from BEHIND the wall, or the only way to
# satisfy the wall would be behind the wall.
# /trips/static/ joins the list because the account page IS the wall — it renders
# the crew card, and the card's stock, foil and variants all live in trips.css.
# Held back, an unfinished guest got the one page they are allowed to see with the
# stylesheet that draws half of it 302'd to the keypad.
#
# /trips/api/prefs/account and /card are here for the same reason: the header slot
# unlocks off having a contact node, not off either form, so someone who owes both
# forms can still legitimately design that much of their card while they are here.
#
# /trips/api/prefs/address-search is the details form's autofill. It is on this
# list rather than blocked because the details form is the ONE thing a guest who
# owes both forms is here to fix, and an address field that only autofills after
# the wall comes down is an address field that never autofills for the person
# most likely to be typing one for the first time. It carries no subject — a
# query string in, public map data out — so there is nothing behind the wall for
# it to reach.
_PREFS_EXEMPT = (
    "/gate", "/static/", "/trips/static/", "/robots.txt", "/trips/api/prefs/me",
    "/trips/api/prefs/form", "/trips/api/prefs/submit", "/trips/api/prefs/account",
    "/trips/api/prefs/card", "/trips/api/prefs/address-search", "/hub-modules.js",
    "/jsx/static/js/topbar.jsx", "/jsx/trips/frontend/static/trip-intake.jsx",
    "/jsx/trips/frontend/static/trips-cost.jsx", "/jsx/trips/frontend/static/trips-landing.jsx",
    "/jsx/trips/frontend/static/addr-combo.jsx", "/jsx/trips/frontend/static/account-core.jsx",
    "/jsx/trips/frontend/static/account.jsx",
    "/jsx/trips/frontend/static/trips-core.jsx",
    "/jsx/trips/frontend/static/trips-nav.jsx",
    "/jsx/trips/frontend/static/trips-transit.jsx",
    "/jsx/trips/frontend/static/trips-money.jsx",
    "/jsx/trips/frontend/static/trips-daymap.jsx",
    "/jsx/trips/frontend/static/trips-flights.jsx",
    "/jsx/trips/frontend/static/trips-tickets.jsx",
    "/jsx/trips/frontend/static/trips-housing.jsx",
    "/jsx/trips/frontend/static/trips-crew.jsx",
    "/jsx/trips/frontend/static/trips-context.jsx",
    "/jsx/trips/frontend/static/trips-board.jsx",
    "/jsx/trips/frontend/static/trips-editors.jsx",
    "/jsx/trips/frontend/static/trips-selfcheck.jsx",
    "/jsx/trips/frontend/static/trips.jsx",
)

_CODE_RE = re.compile(r"^\d{4}$")
_MAX_NAME = 40
# Contact details, typed by anyone on the internet. Length caps only: the point
# is to stop a megabyte landing in the table, not to argue with someone about
# what a real phone number looks like. Sam reads these, not a dialler.
_MAX_PHONE = 30
_MAX_EMAIL = 120
# Optional, unlike the other three: the gate asks for it nowhere, and someone who
# joined before the field existed should not be blocked from saving a phone fix.
_MAX_ADDRESS = 200
# Loose on purpose — something@something. Anything stricter rejects real
# addresses, and this one is never used to send mail.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_PENDING = 100

# ponytail: in-memory counters, so a restart forgives everyone. Deliberate — the
# alternative is a table and a cleanup job for a friends-only itinerary. Move it
# into SQLite if the gate ever guards something that matters.
_FAILS: dict[str, list[float]] = {}
_SIGNUPS: dict[str, list[float]] = {}
_FAIL_LIMIT, _FAIL_WINDOW = 10, 300      # 10 wrong codes from one IP → 5 min cooldown
_SIGNUP_LIMIT, _SIGNUP_WINDOW = 10, 3600  # 10 signup requests per IP per hour

# Per-IP alone is a speed bump, not a wall. The identity it partitions on is a
# header, and anything reaching this port outside the funnel can set that header
# to a new value on every request — so on its own it does not bound a walk of a
# 10,000-entry code space at all.
#
# The bound is the strike system in trips_db.record_gate_failure: wrong codes
# accumulate, each filled window shuts the keypad for twice as long as the last,
# and the fifth strike stops reopening on a clock and waits for Sam. It lives
# in SQLite rather than up here, because this unit runs Restart=always and an
# in-memory counter hands an attacker a clean slate for the price of a crash.
#
# It costs an unlocked guest nothing: a live session never posts here, so a freeze
# can only delay a NEW unlock. That asymmetry is what makes it safe to be blunt.


# 'unsafe-inline' for script-src is not a shrug — gate.html, trips-landing.html
# and trips.html each carry inline <script> blocks, and nonce-ing them means
# editing templates Hub renders too. What the policy still buys on a public page
# is the part that matters: no script from another origin, no framing, no <base>
# rewrite, no form posting elsewhere, and img/connect held to the two hosts the
# board actually talks to (OSM tiles, OSRM routing).
_CSP = "; ".join((
    "default-src 'self'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self' 'unsafe-inline'",
    # Google Fonts is gone from every trips template — the faces are vendored
    # under /static/vendor/fonts/ and served from this origin, so 'self' covers
    # both the stylesheet and the woff2 files.
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    # manifest-src falls back to default-src per spec, but naming it means a
    # future default-src change cannot silently break Add to Home Screen.
    "manifest-src 'self'",
    # One tile host, still. The day-of getting-there card changes its basemap with
    # the tab you are on — dark under the Uber route, washed out under Lyft's — but
    # it does that with a CSS filter over these same OSM tiles rather than by
    # reaching for a second CDN. Carto's free basemaps started demanding an API key
    # (their tiles now render watermarked "API KEY REQUIRED"), and a styled map is
    # not worth a paid dependency, a key in the repo, and a second host on this line.
    "img-src 'self' data: https://server.arcgisonline.com",
    "connect-src 'self' https://router.project-osrm.org",
))

# How stale `last_seen` is allowed to get before the gate moves it. The access
# panel reads that column as "last online", and `ago()` rounds to whole minutes
# and then to whole hours, so five minutes of slack costs the reading nothing and
# saves a database write on every asset and API call a board page makes.
_SEEN_THROTTLE_MINUTES = 5


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(_SHARED_STATIC),
        static_url_path="/static",
    )
    app.config["GUEST"] = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    # Its own signing key, never Hub's: this is the internet-facing process, and a
    # key leaked here must not be able to forge a session on the private one.
    app.secret_key = config.load_or_create_secret_key(
        _DASHBOARD / ".session_secret_public", "TRIPS_PUBLIC_SECRET_KEY"
    )
    # Cookies are NOT port-scoped. Hub serves the same hostname on 5002 and uses
    # Flask's default cookie name, so leaving this at the default would have the
    # two surfaces overwrite each other's session — and, with different keys,
    # mutually invalidate them. Opening the public itinerary would quietly log
    # Sam out of Hub.
    app.config["SESSION_COOKIE_NAME"] = "trips_guest"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Right for the funnel, which is HTTPS. Off for plain-http localhost and the
    # test client, where a Secure cookie is never stored and the gate would become
    # an infinite redirect.
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("TRIPS_PUBLIC_INSECURE") != "1"
    app.permanent_session_lifetime = timedelta(days=30)
    app.config["MAX_CONTENT_LENGTH"] = 4096

    trips_db.init(vault_root() / "data" / "trips.db")
    app.register_blueprint(trips_api.bp)

    # What the two list routes may show, and who the board orders first for.
    # The shared blueprint reads these off app.config; without them installed,
    # api._scoped serves nothing rather than everything.
    app.config["TRIP_SCOPE"] = _allowed_trips
    app.config["VIEWER"] = _viewer_key

    # Registration order matters here: before_request hooks run in the order
    # registered, after_request hooks run in reverse. _static_allowlist first,
    # so a path off the list is gone before any other hook has an opinion.
    app.before_request(_static_allowlist)
    app.teardown_request(_release_sqlite)
    app.after_request(zoom_lock.lock_zoom)
    app.after_request(_harden)
    app.before_request(_intake_body_limit)
    app.before_request(_read_only_gate)
    app.before_request(_gate)

    # A fixed key, not one derived from the session secret: that secret is
    # per-machine and gitignored, so the PC and the Mac each minted a different
    # link and the one texted to the crew only worked on the machine that made it.
    # ponytail: the key lives in a private repo, which is as private as the page
    # needs. Change it to kill every link already sent.
    app.config["LOSTLANDS_PATH"] = f"/lostlands/{_LL_KEY}/"
    app.add_url_rule("/lostlands/<key>/", "lostlands_open", lostlands_open)
    app.add_url_rule("/lostlands/<key>/f/<name>", "lostlands_file", lostlands_file)
    app.add_url_rule("/lostlands/<key>/sw.js", "lostlands_worker", lostlands_worker)

    app.add_url_rule("/hub-modules.js", "hub_modules_js", hub_modules_js)
    app.add_url_rule("/jsx/static/js/topbar.jsx", "topbar_jsx", topbar_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/trip-intake.jsx", "trip_intake_jsx", trip_intake_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/trips-cost.jsx", "trips_cost_jsx", trips_cost_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/trips-landing.jsx", "trips_landing_jsx", trips_landing_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/addr-combo.jsx", "addr_combo_jsx", addr_combo_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/account-core.jsx", "account_core_jsx", account_core_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/account.jsx", "account_jsx", account_jsx)
    app.add_url_rule("/jsx/trips/frontend/static/trips-core.jsx", "trips_core_jsx", _trips_part_jsx("trips-core"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-nav.jsx", "trips_nav_jsx", _trips_part_jsx("trips-nav"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-transit.jsx", "trips_transit_jsx", _trips_part_jsx("trips-transit"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-money.jsx", "trips_money_jsx", _trips_part_jsx("trips-money"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-daymap.jsx", "trips_daymap_jsx", _trips_part_jsx("trips-daymap"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-flights.jsx", "trips_flights_jsx", _trips_part_jsx("trips-flights"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-tickets.jsx", "trips_tickets_jsx", _trips_part_jsx("trips-tickets"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-housing.jsx", "trips_housing_jsx", _trips_part_jsx("trips-housing"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-crew.jsx", "trips_crew_jsx", _trips_part_jsx("trips-crew"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-context.jsx", "trips_context_jsx", _trips_part_jsx("trips-context"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-board.jsx", "trips_board_jsx", _trips_part_jsx("trips-board"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-editors.jsx", "trips_editors_jsx", _trips_part_jsx("trips-editors"))
    app.add_url_rule("/jsx/trips/frontend/static/trips-selfcheck.jsx", "trips_selfcheck_jsx", _trips_part_jsx("trips-selfcheck"))
    app.add_url_rule("/jsx/trips/frontend/static/trips.jsx", "trips_jsx", _trips_part_jsx("trips"))
    app.add_url_rule("/", "root", root)
    app.add_url_rule("/robots.txt", "robots", robots)
    public_area.register(app)

    # ── The gate ──────────────────────────────────────────────────────────
    app.add_url_rule("/gate", "gate", gate)
    app.add_url_rule("/gate", "gate_submit", gate_submit, methods=["POST"])
    app.add_url_rule("/gate/prefs", "gate_prefs", gate_prefs)
    app.add_url_rule("/gate/me", "gate_me", gate_me, methods=["POST"])
    app.add_url_rule("/gate/logout", "gate_logout", gate_logout)
    app.add_url_rule("/gate/request", "gate_request", gate_request, methods=["POST"])
    app.add_url_rule("/gate/out", "gate_out", gate_out)

    return app


# ── Sections (Task 6 of the trips-split plan) ───────────────────────────────
# Imported last, so every module-level name above already exists by the time
# create_app() below runs. Explicit re-exports, not `import *`, because that
# drops the underscore names tests hold onto (e.g. public_app._prefs_done) and
# because test_trips_facades.py's identity check requires every top-level
# section function to resolve on this facade as the same object.
from .public_gate import (  # noqa: E402,F401
    _allowed_trips, _client_ip, _gate, _guest_code, _json_body, _prefs_done,
    _read_only_gate, _record, _too_many, _viewer_key, gate, gate_logout,
    gate_me, gate_out, gate_prefs, gate_request, gate_submit,
)
from .public_hooks import (  # noqa: E402,F401
    _harden, _intake_body_limit, _release_sqlite, _static_allowlist, hub_modules_js, robots, root,
    topbar_jsx,
)
from .public_lostlands import (  # noqa: E402,F401
    _ll_ok, _ll_slim_trip, lostlands_file, lostlands_open, lostlands_worker,
)

def trip_intake_jsx():
    # The guest form's body, transpiled like topbar_jsx. One file, not Hub's /jsx/ route.
    import jsx_build
    resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / "trip-intake.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def trips_cost_jsx():
    # The landing page's cost component, transpiled like trip_intake_jsx.
    import jsx_build
    resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / "trips-cost.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def trips_landing_jsx():
    # The landing page body, transpiled like trip_intake_jsx.
    import jsx_build
    resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / "trips-landing.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def addr_combo_jsx():
    # The address combobox the account page's details form uses, transpiled like trip_intake_jsx.
    import jsx_build
    resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / "addr-combo.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def account_core_jsx():
    # The account page's card, nav, details and preference blocks, transpiled like trip_intake_jsx.
    import jsx_build
    resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / "account-core.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def account_jsx():
    # The account page body, transpiled like trip_intake_jsx.
    import jsx_build
    resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / "account.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _trips_part_jsx(name):
    # One of the trips board's JSX parts, transpiled like trip_intake_jsx.
    def view():
        import jsx_build
        resp = make_response(jsx_build.transpile(_TRIPS_DIR / "frontend" / "static" / f"{name}.jsx"))
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"
        return resp
    return view


app = create_app()


def serve(port: int = DEFAULT_PORT) -> None:
    """Run the public mirror. Called from the script guard near the top."""
    # Keep-alive plus an IPv6 listener beside the IPv4 one — same fix as Hub's
    # app.py (2026-09-04): from Windows, `localhost` tries ::1 first and each
    # closed connection paid ~200ms. V6ONLY so both sockets share the port; the
    # IPv4 one stays because WSL's relay hangs 127.0.0.1 when only :: listens.
    import socket
    import threading
    from werkzeug.serving import WSGIRequestHandler, make_server
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    v6.bind(("::", port))
    v6.listen(128)
    threading.Thread(
        target=make_server("::", port, app, threaded=True, fd=v6.fileno()).serve_forever,
        daemon=True,
    ).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)  # noqa: S104 -- LAN/Tailscale-only dashboard, intended reachable from every interface
