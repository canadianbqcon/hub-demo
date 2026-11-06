"""Response hardening and the two misc routes every page needs before login.

Split from trips/public_app.py (Task 6 of the 2026-09-24 trips-split plan).
Reaches every public_app global through the `_pa` alias at call time (never
`from .public_app import ...`). See dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import json

from flask import make_response, redirect, request

import sqlite_helpers

from . import public_app as _pa


def _static_allowlist():
    """Only the board's own assets leave this process. See _pa._STATIC_ALLOW.

    Registered first, so a path that is not on the list is gone before any
    other hook has an opinion about it. `..` is rejected outright rather than
    left to safe_join, because the check above it is a prefix test and a
    prefix test is exactly what a traversal is built to satisfy.
    """
    if not request.path.startswith("/static/"):
        return None
    rel = request.path[len("/static/"):]
    if ".." in rel or not (rel in _pa._STATIC_ALLOW or rel.startswith(_pa._STATIC_ALLOW_DIRS)):
        return {"error": "not found"}, 404
    return None


def _intake_body_limit():
    """Lift the 4 KB body cap to 64 KB for the intake POST and nothing else.
    Runs before any hook or view reads the body, which is when Flask enforces it."""
    if request.method == "POST" and _pa._INTAKE_POST.match(request.path):
        request.max_content_length = _pa._INTAKE_MAX_BYTES


def _release_sqlite(_exc):
    """Same per-request SQLite release Hub does — see hub/app.py."""
    sqlite_helpers.close_scoped()


def _harden(resp):
    """Headers a shared itinerary needs: it carries addresses, flight numbers
    and everyone's arrival times.

    setdefault, never assignment — a route that has already decided its own
    caching or content type keeps it.
    """
    resp.headers.setdefault("Content-Security-Policy", _pa._CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # frame-ancestors above covers modern browsers; this covers the rest.
    resp.headers.setdefault("X-Frame-Options", "DENY")
    # The board links out to Expedia, Turo, flightradar. Without this the
    # share URL itself rides along in the Referer to every one of them.
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    # Only meaningful over the funnel, which is HTTPS. Browsers ignore it on
    # the plain-http localhost the tests and the LAN use, so it is safe to
    # send unconditionally.
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


def topbar_jsx():
    # The shared top bar, transpiled the same way Hub's /jsx/ route does it. Only
    # this one file: Hub's /jsx/ would hand out every module's source.
    import jsx_build
    resp = make_response(jsx_build.transpile(_pa._HUB_DIR / "static" / "js" / "topbar.jsx"))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def hub_modules_js():
    # The shared topbar reads window.MODULES to build its module switcher.
    # Hub serves the real fifteen; this serves an empty list, so the switcher
    # renders with nothing to switch to instead of advertising modules that
    # do not exist on this port.
    resp = make_response("window.MODULES=" + json.dumps([]) + ";")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def root():
    # Hub's home does not exist here, and the topbar brand links to "/".
    # Send it to the trip list rather than 404 on a click.
    return redirect("/trips/")


def robots():
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain"}
