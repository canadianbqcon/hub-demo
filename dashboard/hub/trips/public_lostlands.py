"""The open Lost Lands link — one festival page behind a bare key, no gate.

Split from trips/public_app.py (Task 6 of the 2026-09-24 trips-split plan).
Reaches every public_app global through the `_pa` alias at call time (never
`from .public_app import ...`), so a test's monkeypatch on the facade (its
`_LL_TRIP_ID`) still lands here. See dashboard/hub/tests/test_trips_facades.py.

/lostlands/<key>/ is the festival page with nothing to type (2026-09-18: the
crew is inside a venue with no signal, and a keypad plus two forms is not a
thing to walk someone through in a field). "/lostlands/" is public in the
facade's _PUBLIC_PREFIXES, so the KEY is the whole gate: every route under it
404s on a wrong one.

It is deliberately NOT /trips/<id> with the gate lifted. That board's data call
ships full rows: the crew's emails and home addresses, the hotel confirmation
and wifi password, flight confirmation numbers. This page gets _ll_slim_trip()
and nothing else, and its files come from the facade's fixed _LL_FILES table,
so a key holder can reach exactly one page and the five files it loads.
"""

from __future__ import annotations

import hmac

from flask import make_response, render_template

from . import db as trips_db
from . import public_app as _pa


def _ll_slim_trip() -> dict | None:
    """The three things lostlands.js reads off the trip, and no other column."""
    t = trips_db.get_full_trip(_pa._LL_TRIP_ID)
    if not t:
        return None
    return {
        "id": t["id"], "name": t.get("name"),
        "start_date": t.get("start_date"), "end_date": t.get("end_date"),
        "members": [{"id": m.get("id"), "name": m.get("name"), "contact_slug": m.get("contact_slug")}
                    for m in t.get("members") or []],
        "housing": [{"name": h.get("name"), "address": h.get("address"), "status": h.get("status")}
                    for h in t.get("housing") or []],
        # confirmation is withheld: it is the bus order's purchase number
        "transportation": [{"description": x.get("description"), "split_with": x.get("split_with"), "confirmation": ""}
                           for x in t.get("transportation") or []],
    }


def _ll_ok(key: str) -> bool:
    return hmac.compare_digest(key, _pa._LL_KEY)


def lostlands_open(key: str):
    trip = _ll_slim_trip() if _ll_ok(key) else None
    if not trip:
        return {"error": "not found"}, 404
    resp = make_response(render_template("lostlands-open.html", trip=trip, base=f"/lostlands/{key}/"))
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def lostlands_file(key: str, name: str):
    if not _ll_ok(key) or name not in _pa._LL_FILES:
        return {"error": "not found"}, 404
    path, ctype = _pa._LL_FILES[name]
    resp = make_response(path.read_bytes())
    resp.headers["Content-Type"] = ctype
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    return resp


def lostlands_worker(key: str):
    # Hub's own offline worker, served from under this page's path so its scope
    # is this page alone. The gated board gets no worker: a revoked guest must
    # not keep a saved copy of it. See dashboard/CLAUDE-hub-offline.md.
    if not _ll_ok(key):
        return {"error": "not found"}, 404
    resp = make_response((_pa._HUB_DIR / "static" / "js" / "sw.js").read_text())
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    return resp
