"""Geocoding: batch pin placement over a trip's housing/activities/transport/
homes/airports, plus the walkable-radius lookup around one stay.

Split from trips/api.py (Task 4 of the 2026-09-24 trips-split plan; this
sub-file split out of the first draft of api_places.py, which came in over
500 lines by itself). Reaches every trips.api global through the `_api`
alias and every trips.db function through `db`, both by attribute at call
time (never `from .api import ...` / `from .db import ...`), so a test's
monkeypatch on either facade still lands here — `_api.geocode_mod` and
`_api.nearby_mod` are both patched by name in the test suite. See
dashboard/hub/tests/test_trips_facades.py.

`_placed` and `api_geocode_trip` (with its nested `near_enough` and
`note_move` helpers) are read as SOURCE TEXT by
dashboard/hub/tests/test_geocode_write_gate.py, which was updated to point
at this file when the route moved here — the behavioural guarantees it pins
(the distance gate cannot silently switch itself off; a skip always reads
both halves of a coordinate) are unchanged.
"""

from __future__ import annotations

import re

from flask import jsonify, request

from . import api as _api
from . import db


# ── Geocoding (batch over a trip's housing + activities) ──────────────────────


def _address_of(location: str) -> str:
    """The mappable half of a transportation row's `location`.

    Rental rows describe the counter before they name it — "Off-airport, free
    shuttle to counter and car (6130 N Jackson Gap Way, Aurora)". Nominatim
    answers nothing for the sentence and the street address for the tail, so the
    parenthesised part wins when it exists. Mirrors carAddr() in trips.js.
    """
    m = re.search(r"\(([^)]+)\)\s*$", location or "")
    return (m.group(1) if m else (location or "")).strip()


def _transport_where(row: dict, dest: str) -> str:
    """Where a transportation row IS, for geocoding purposes.

    A rental row is a counter with a street address in `location`. A ride is not
    anywhere — it is a leg — so `location` is empty on every train and rideshare
    on the board and all of them were skipped. What a ride does have is `arrival`,
    the place it puts you: "Denver Union Station", "Denver (RiNo / LoDo)". That is
    the coordinate the arrival read needs to say how long it takes to get into the
    city and how long you have there.

    The trip's destination is appended when the arrival names no city of its own,
    because "Union Station" is a building in a dozen countries.
    """
    where = _address_of(row.get("location") or "")
    if where:
        return where
    arrival = _address_of(row.get("arrival") or "").strip()
    if not arrival:
        return ""
    city = (dest or "").split(",")[0].strip()
    return arrival if not city or city.lower() in arrival.lower() else f"{arrival}, {dest}"


# Everything a trip pins except an airport sits at the destination: the stay, the
# activities, the off-airport rental counters. A result hundreds of miles from
# there is not an imprecise pin, it is a different place — a run of this route
# once wrote a Denver rental counter into central France, others into Panama,
# Germany and south Texas, and an activity into London. A wrong pin is worse than
# no pin: nulls render as "not on the map yet", wrong ones render as answers and
# feed the map, the distances and the drive times off them.
#
# 150 mi, not 100: a legitimate day trip out of the destination city is real
# (Rocky Mountain NP is ~65 mi from Denver) and the radius has to clear it with
# margin. Every bad pin the corrupting run produced was 700+ mi out, so the slack
# costs nothing. ponytail: one radius, no per-trip field — widen the constant if a
# trip ever legitimately spans more than that.
GEO_MAX_MI = 150


def _placed(row: dict) -> bool:
    """Is this row actually ON the map?

    A pin is a PAIR. Every skip below used to read `lat is not None` alone, so a
    row holding a latitude and a null longitude counted as placed and was skipped
    forever — half a coordinate, unplottable, and unreachable by the one route
    that could repair it. Reading both makes the same loop the repair path.
    """
    return row.get("lat") is not None and row.get("lng") is not None


def _geo_anchor(trip: dict) -> tuple[float, float] | None:
    """Where this trip's non-airport pins have to be near.

    A stay that is already placed is the best anchor because it is a street
    address somebody booked. Falling back to the destination city keeps the gate
    alive on a trip where nothing is geocoded yet — without it the first pass on a
    fresh trip would be ungated, which is exactly the pass that corrupted trip 61.
    """
    for h in trip.get("housing", []):
        if h.get("lat") is not None and h.get("lng") is not None:
            return (float(h["lat"]), float(h["lng"]))
    dest = (trip.get("destination") or "").strip()
    if not dest:
        return None
    coords = _api.geocode_mod.geocode(dest)
    return coords if coords else None


@_api.bp.route("/api/trips/<int:trip_id>/geocode", methods=["POST"])
def api_geocode_trip(trip_id):
    trip = db.get_full_trip(trip_id, with_home=True)
    if not trip:
        return jsonify({"error": "not found"}), 404
    if not _api.geocode_mod:
        return jsonify({"error": "geocoder unavailable"}), 503

    anchor = _geo_anchor(trip)
    rejected = []

    # Every loop below skips a row that is already placed, which is right for the
    # normal pass and is also why a wrong pin used to be PERMANENT: the one route
    # that could repair it was the one route that refused to look at it, so fixing
    # the geocoding logic could never repair a trip the old logic had corrupted.
    #
    # `force` reopens exactly those rows. It is off by default and has to be asked
    # for, because nothing on these tables records whether a pin came from the
    # geocoder or from somebody correcting it by hand — so a re-check cannot tell
    # the two apart and a blanket re-run would quietly undo the corrections. Making
    # it explicit puts that call where it belongs.
    #
    # A forced re-check is NOT a licence to write worse data: it goes through the
    # same near_enough gate, and a result that fails the gate leaves the existing
    # pin exactly where it is rather than nulling it. Anything that does move comes
    # back in `moved` with the distance, so a surprising overwrite is visible in the
    # response instead of being discovered on the map weeks later.
    #
    # ponytail: no provenance column. Add `geo_source` to the four tables if hand
    # corrections ever start getting clobbered often enough to be worth a migration.
    force = bool((request.get_json(silent=True) or {}).get("force"))
    moved = []

    def note_move(label, before, after, shared=False):
        """Record a forced re-check that actually changed where something sits."""
        if not (before and before[0] is not None and before[1] is not None):
            return
        b = (float(before[0]), float(before[1]))
        if abs(b[0] - after[0]) < 1e-9 and abs(b[1] - after[1]) < 1e-9:
            return
        entry = {"what": label, "from": b, "to": [after[0], after[1]],
                 "miles": round(_api.geocode_mod.miles_between(b, after), 1)}
        if shared:
            # Airports and crew homes are keyed globally, not per trip, so moving one
            # here moves it on every other trip that shares it. Say so.
            entry["shared"] = True
        moved.append(entry)

    def near_enough(coords, label):
        """True when this result is close enough to the trip to be written.

        No anchor means the gate has nothing to measure against, and the old
        `return bool(coords)` there did not degrade it — it turned it OFF, and
        wrote whatever Nominatim said with no geographic check at all. That is
        the state a fresh trip is in, which is exactly the pass that once wrote
        a Denver rental counter into central France. Refusing is the safe half
        of the same choice the rest of this route already makes: a null renders
        as "not on the map yet", a wrong pin renders as an answer.

        Reaching here needs a trip with no placed stay AND no destination that
        resolves, so the fix is one field on the trip. It is reported in
        `rejected` rather than counted silently as a geocoder failure.

        Callers guard the falsy-coords case themselves (`not coords or not
        near_enough(...)`) rather than this function doing it, so this nested
        closure's own branch count stays out of api_geocode_trip's mccabe
        score — a bare geocode miss is still a silent False either way.
        """
        if not anchor:
            _api.logger.warning("geocode refused for %s: the trip has no anchor", label)
            rejected.append({"what": label, "miles": None,
                             "why": "no anchor — set the trip's destination"})
            return False
        mi = _api.geocode_mod.miles_between(anchor, coords)
        if mi <= GEO_MAX_MI:
            return True
        _api.logger.warning("geocode rejected for %s: %.0f mi from the trip (%s)", label, mi, coords)
        rejected.append({"what": label, "miles": round(mi)})
        return False

    housing = _geocode_housing_rows(trip, trip_id, force, near_enough, note_move)
    activities = _geocode_activity_rows(trip, trip_id, force, near_enough, note_move)
    transport = _geocode_transport_rows(trip, trip_id, force, near_enough, note_move)
    homes = _geocode_home_rows(trip, trip_id, force, near_enough, note_move)
    airports = _geocode_airport_rows(trip, trip_id, force, near_enough, note_move)
    updated = housing[0] + activities[0] + transport[0] + homes[0] + airports[0]
    skipped = housing[1] + activities[1] + transport[1] + homes[1] + airports[1]
    failed = housing[2] + activities[2] + transport[2] + homes[2] + airports[2]

    return jsonify(
        {"updated": updated, "skipped": skipped, "failed": failed, "rejected": rejected,
         "forced": force, "moved": moved,
         "trip": db.get_full_trip(trip_id, with_home=True)}
    )


# The five loops below are top-level, not nested in api_geocode_trip, on
# purpose: a nested `def`'s own branches roll into the ENCLOSING function's
# mccabe score (measured — see the plan's pending notes), so nesting them
# the way `note_move`/`near_enough` are nested would not have lowered
# api_geocode_trip's complexity at all. `near_enough` and `note_move` stay
# nested because test_geocode_write_gate.py reads them as source text
# immediately inside api_geocode_trip's body; these five take them as
# explicit callables instead of closing over them.


def _trip_country(trip):
    """'Santa Tecla / San Salvador, El Salvador' -> 'El Salvador'. Scopes the
    geocoder's by-name fallback for addresses that carry no US state."""
    dest = (trip.get("destination") or "").strip()
    return dest.rsplit(",", 1)[-1].strip() if "," in dest else None


def _geocode_housing_rows(trip, trip_id, force, near_enough, note_move):
    updated = skipped = failed = 0
    for h in trip.get("housing", []):
        if (_placed(h) and not force) or not (h.get("address") or "").strip():
            skipped += 1
            continue
        was = (h.get("lat"), h.get("lng"))
        coords = _api.geocode_mod.geocode(h["address"], name=h.get("name") or None, country=_trip_country(trip))
        if not coords or not near_enough(coords, h.get("name") or h["address"]):
            coords = None
        if coords:
            db.update_housing(trip_id, h["id"], {"lat": coords[0], "lng": coords[1]})
            note_move(h.get("name") or h["address"], was, coords)
            updated += 1
        else:
            failed += 1
    return updated, skipped, failed


def _geocode_activity_rows(trip, trip_id, force, near_enough, note_move):
    updated = skipped = failed = 0
    for a in trip.get("activities", []):
        if (_placed(a) and not force) or not (a.get("location") or "").strip():
            skipped += 1
            continue
        was = (a.get("lat"), a.get("lng"))
        coords = _api.geocode_mod.geocode(a["location"], name=a.get("name") or None, country=_trip_country(trip))
        if not coords or not near_enough(coords, a.get("name") or a["location"]):
            coords = None
        if coords:
            db.update_activity(trip_id, a["id"], {"lat": coords[0], "lng": coords[1]})
            note_move(a.get("name") or a["location"], was, coords)
            updated += 1
        else:
            failed += 1
    return updated, skipped, failed


# A car pickup has an address like a stay does, so it geocodes in place — but
# `location` on a rental row is prose with the address in the tail: "Off-airport,
# free shuttle to counter and car (6130 N Jackson Gap Way, Aurora)". Handing the
# whole sentence to the geocoder is why every counter on the Denver board still
# had a null lat. Take the parenthesised address when there is one, the same rule
# carAddr() reads by in trips.js.
def _geocode_transport_rows(trip, trip_id, force, near_enough, note_move):
    updated = skipped = failed = 0
    for x in trip.get("transportation", []):
        if _placed(x) and not force:
            skipped += 1
            continue
        was = (x.get("lat"), x.get("lng"))
        where = _transport_where(x, trip.get("destination") or "")
        if not where:
            skipped += 1
            continue
        # No `name=`. The name fallback exists for landmarks Nominatim knows by
        # name but not by street address; a transportation row's description is a
        # car model ("ACE — Dodge Grand Caravan or similar"), and feeding it in is
        # what matched a rental counter to a village in central France. The
        # parenthesised street address is the only thing on the row that names a
        # place, so it is the only thing that gets to.
        coords = _api.geocode_mod.geocode(where)
        if not coords or not near_enough(coords, x.get("description") or where):
            coords = None
        if coords:
            db.update_transport(trip_id, x["id"], {"lat": coords[0], "lng": coords[1]})
            note_move(x.get("description") or where, was, coords)
            updated += 1
        else:
            failed += 1
    return updated, skipped, failed


# Airports resolve from the IATA code into a shared cache, so a code already
# seen on any earlier trip costs nothing here. Deliberately NOT distance-gated:
# a trip has an airport at each end by definition, and LGA is 1,600 mi from a
# Denver stay while being exactly right.
# Crew homes, for the day-of ride chain. Never distance-gated and never
# attempted at all on the public port: `with_home` is false there, so the
# loop simply has nothing to walk. A home is where somebody LIVES — it is
# 1,600 miles from a Denver stay while being exactly right, the same reason
# the airport pass below skips the gate.
def _geocode_home_rows(trip, trip_id, force, near_enough, note_move):
    updated = skipped = failed = 0
    for m in trip.get("members", []):
        home = m.get("home") or {}
        addr = (home.get("address") or "").strip()
        slug = (m.get("contact_slug") or "").strip()
        if not addr or not slug or (_placed(home) and not force):
            skipped += 1
            continue
        was = (home.get("lat"), home.get("lng"))
        # No `name=`. The fallback exists for landmarks known by name rather than
        # by street, and a member's name is a person — feeding one in is how a
        # rental counter once matched a village in central France.
        coords = _api.geocode_mod.geocode(addr)
        if coords:
            db.set_guest_home(slug, coords[0], coords[1])
            note_move(f"{m.get('name') or slug} (home)", was, coords, shared=True)
            updated += 1
        else:
            failed += 1
    return updated, skipped, failed


def _geocode_airport_rows(trip, trip_id, force, near_enough, note_move):
    updated = skipped = failed = 0
    known = trip.get("airports", {})
    for code in db.trip_airport_codes(trip):
        row = known.get(code, {})
        # Two answers live on an airport now and they go missing independently:
        # every airport cached before migration 021 has coordinates and no zone.
        # Gating the whole block on the coordinates alone left those rows "done"
        # forever, so the zone got a condition of its own — but only one skip,
        # and `force` still reopens it (tests/test_geocode_write_gate.py).
        fresh = _placed(row) and not force
        need_tz = not (row.get("tz") or "").strip()
        if fresh and not need_tz:
            skipped += 1
            continue
        was = (row.get("lat"), row.get("lng"))
        coords = was if fresh else _api.geocode_mod.geocode(f"{code} airport")
        if coords:
            # None from the zone lookup means "ask again later"; upsert_airport
            # reads the empty string as "leave what is there".
            tz = _api.geocode_mod.timezone_at(coords[0], coords[1]) if need_tz else ""
            db.upsert_airport(code, coords[0], coords[1], name=f"{code} airport", tz=tz or "")
            note_move(f"{code} airport", was, coords, shared=True)
            updated += 1
        else:
            failed += 1
    return updated, skipped, failed


# ── What's around the stay (Overpass, walkable radius only) ───────────────────


@_api.bp.route("/api/trips/<int:trip_id>/housing/<int:hid>/nearby", methods=["GET"])
def api_housing_nearby(trip_id, hid):
    """The walkable scope around one stay. Keyed on the row, not on free
    coordinates: this route is also reachable on the public share port, and a
    lat/lng parameter would turn it into an open Overpass proxy."""
    if not _api.nearby_mod:
        return jsonify({"error": "nearby lookup unavailable"}), 503
    trip = db.get_full_trip(trip_id)
    if not trip:
        return jsonify({"error": "not found"}), 404
    row = next((h for h in trip.get("housing", []) if h["id"] == hid), None)
    if not row:
        return jsonify({"error": "not found"}), 404
    if row.get("lat") is None or row.get("lng") is None:
        return jsonify({"error": "no coordinates on this stay yet"}), 409
    try:
        return jsonify(_api.nearby_mod.nearby(row["lat"], row["lng"]))
    except Exception as e:
        _api.logger.warning("nearby lookup failed for housing %s: %s", hid, e)
        return jsonify({"error": "lookup failed"}), 502


