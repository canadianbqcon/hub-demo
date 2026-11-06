"""Trip CRUD, summary and guest-redaction routes.

Split from trips/api.py (Task 3 of the 2026-09-24 trips-split plan). Reaches
every trips.api global through the `_api` alias and every trips.db function
through `db`, both by attribute at call time (never `from .api import ...` /
`from .db import ...`), so a test's monkeypatch on either facade still lands
here. See dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

from flask import current_app, jsonify, request

from . import api as _api
from . import db


def _scoped(trips: list[dict]) -> list[dict]:
    """Cut a trip list down to what the caller may see.

    The two list routes are the only ones with no trip id in the path, so the
    public mirror's `before_request` guard — which reads `view_args` — cannot
    reach them. They filter here instead, through a callable the gated process
    installs as TRIP_SCOPE. Hub never sets it and its behaviour is unchanged.

    Fails CLOSED. "No callable" means everything, which is right for Hub and a
    silent full disclosure if the public app ever failed to install one, so
    guest mode without a scope yields nothing rather than the whole board: a
    wiring bug then shows an empty page instead of everyone's trips.
    """
    previewing = _api._preview_slug()
    if previewing:
        # Hub has no TRIP_SCOPE of its own — it is the private port and shows
        # everything — so the preview supplies one for as long as it is on.
        return [t for t in trips if t["id"] in db.trips_for_slug(previewing)]
    scope = current_app.config.get("TRIP_SCOPE")
    if scope is None:
        if current_app.config.get("GUEST", False):
            _api.logger.error("GUEST app has no TRIP_SCOPE — serving no trips rather than all")
            return []
        return trips
    allowed = scope()
    return [t for t in trips if t["id"] in allowed]


@_api.bp.route("/api/trips", methods=["GET"])
def api_list_trips():
    _api._reconcile_deleted_trips()  # daily-gated; reflects gcal deletions back to the DB
    return jsonify(_scoped(db.list_trips()))


@_api.bp.route("/api/trips/summary", methods=["GET"])
def api_trips_summary():
    """The landing page's only fetch: every trip plus its planning counts and
    its raw scheduled rows (next-up is picked client-side by triptime.js —
    see db.list_trips_summary for why it can't be done in SQL)."""
    _api._reconcile_deleted_trips()
    return jsonify(_scoped(db.list_trips_summary()))


@_api.bp.route("/api/trips", methods=["POST"])
def api_create_trip():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    trip = db.create_trip(data)
    if _api._cal_ready() and not data.get("cal_event_id"):
        try:
            cal_event_id = _api.gcal.push_trip(trip)
            db.set_trip_cal_event_id(trip["id"], cal_event_id)
            trip["cal_event_id"] = cal_event_id
        except Exception:
            _api.logger.exception("push_trip failed")
    return jsonify(trip), 201


def _redact_notes(text: str) -> str:
    """Drop the account-number lines from one free-text field, keep the rest.

    Line-wise rather than a global substitution, because "Ticket: 5262189549262"
    should leave nothing behind — a bare "Ticket:" with the number blanked out
    still tells a reader there is a number to go looking for.
    """
    if not text:
        return text
    kept = [
        _api._LONG_DIGITS.sub("•••", line)
        for line in text.splitlines()
        if not _api._SECRET_LABELS.match(line)
    ]
    return "\n".join(kept).strip()


def _hide_home_addresses(trip: dict) -> None:
    """Drop each member's street text, keep the point it geocodes to.

    `_attach_homes` puts a crew member's home on the payload so the day-of ride
    chain can order the pickups furthest-first — Sam widened `guest_codes.
    address` to co-travellers on 2026-08-28 for exactly that. The chain only ever
    needs the COORDINATES: it sorts by distance and asks OSRM for drive times, and
    neither reads the string. So the string goes and the point stays, which keeps
    the feature working while a guest no longer reads where anyone lives.
    (2026-09-10, reversing the street-text half of that widening.)

    The key STAYS even when there are no coordinates yet, carrying nothing. That
    is load-bearing: `_attach_homes` only attaches `home` at all for a member whose
    account holds an address, so its mere presence is the fact "this person has
    given us one" with the text removed. Dropping it would have made an address
    that is on file but will not geocode look identical to no address at all, and
    the ride card names the second group — so Owen Hale, whose address IS on file
    and does not place, would have been asked again for the thing he already gave.
    That distinction is guarded by tests/test_trips_ride_gaps.py.
    """
    for m in trip.get("members", []):
        home = m.get("home")
        if not isinstance(home, dict):
            continue
        m["home"] = {k: home[k] for k in ("lat", "lng") if home.get(k) is not None}


def _redact_for_guest(trip: dict) -> dict:
    """Strip account numbers from every free-text field a guest can read.

    Applied to the payload on its way out rather than to the row on its way in,
    so `data/trips.db` is untouched and Hub keeps rendering the numbers Sam
    put there. The mirror and Hub run the same code off the same disk; the only
    thing that differs is whether GUEST is set.
    """
    _hide_home_addresses(trip)
    trip.pop("flight_research", None)  # his own fare shopping, not the crew's
    for table in _api._GUEST_TEXT_TABLES:
        rows = trip.get(table)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if table == "flights":
                # Sam, 2026-10-13: flight notes are his own record (ticket and
                # loyalty numbers, who moved onto whose flight), never the guest's.
                row["notes"] = ""
                continue
            for field in _api._GUEST_TEXT_FIELDS:
                if isinstance(row.get(field), str):
                    row[field] = _redact_notes(row[field])
    return trip


@_api.bp.route("/api/trips/<int:trip_id>", methods=["GET"])
def api_get_trip(trip_id: int):
    # Homes on both surfaces: the ride chain is for the crew, who read this on the
    # mirror, not only for Sam on Hub. See db.get_full_trip on the scope.
    trip = db.get_full_trip(trip_id, with_home=True)
    if not trip:
        return jsonify({"error": "not found"}), 404
    # The one route that ships full rows, so the one place the numbers can leak.
    # The landing-card query names its columns and never selects notes.
    if _api._guest_mode():
        trip = _redact_for_guest(trip)
    return jsonify(trip)


@_api.bp.route("/api/trips/<int:trip_id>", methods=["PATCH"])
def api_update_trip(trip_id: int):
    data = request.get_json(force=True, silent=True) or {}
    trip = db.update_trip(trip_id, data)
    if not trip:
        return jsonify({"error": "not found"}), 404
    if _api._cal_ready() and trip.get("cal_event_id"):
        try:
            _api.gcal.push_trip(trip)
        except Exception:
            _api.logger.exception("push_trip update failed")
    return jsonify(trip)


@_api.bp.route("/api/trips/<int:trip_id>", methods=["DELETE"])
def api_delete_trip(trip_id: int):
    trip = db.get_trip(trip_id)
    if trip and trip.get("cal_event_id") and _api._cal_ready():
        try:
            _api.gcal.delete_event(trip["cal_event_id"])
        except Exception:
            _api.logger.exception("delete_event failed")
    return jsonify({"ok": db.delete_trip(trip_id)})
