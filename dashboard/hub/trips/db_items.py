"""Trip sub-resources: housing, flights, transportation, expenses, activities,
packing ticks, the shared grocery list, and the derived "Leave home base"
departures.

Split out of trips/db.py (Task 2). Field allow-lists and the departure-timing
constants stay on the facade (Rule 1) and are reached here as `db.<name>` at
call time, same as `db._conn`/`db._row*`.
"""

from __future__ import annotations

import re

from . import db


# ── Housing ───────────────────────────────────────────────────────────────────
# `_HOUSING_FIELDS` lives on the facade (db._HOUSING_FIELDS) — see migration
# notes there for what each column is.


def add_housing(trip_id, data):
    return db._settle("housing", trip_id, db._add("housing", trip_id, data, db._HOUSING_FIELDS))


def update_housing(trip_id, hid, data):
    return db._settle("housing", trip_id, db._update("housing", hid, trip_id, data, db._HOUSING_FIELDS))


def delete_housing(trip_id, hid):
    return db._delete("housing", hid, trip_id)


# ── Flights ───────────────────────────────────────────────────────────────────


def add_flight(trip_id, data):
    return db._settle("flights", trip_id, db._add("flights", trip_id, data, db._FLIGHT_FIELDS))


def update_flight(trip_id, fid, data):
    return db._settle("flights", trip_id, db._update("flights", fid, trip_id, data, db._FLIGHT_FIELDS))


def delete_flight(trip_id, fid):
    return db._delete("flights", fid, trip_id)


# ── Transportation ────────────────────────────────────────────────────────────


def add_transport(trip_id, data):
    return db._add("transportation", trip_id, data, db._TRANSPORT_FIELDS)


def update_transport(trip_id, tid, data):
    return db._update("transportation", tid, trip_id, data, db._TRANSPORT_FIELDS)


def delete_transport(trip_id, tid):
    return db._delete("transportation", tid, trip_id)


# ── Expenses ──────────────────────────────────────────────────────────────────


def add_expense(trip_id, data):
    return db._add("expenses", trip_id, data, db._EXPENSE_FIELDS)


def update_expense(trip_id, eid, data):
    return db._update("expenses", eid, trip_id, data, db._EXPENSE_FIELDS)


def delete_expense(trip_id, eid):
    return db._delete("expenses", eid, trip_id)


# ── Grocery ───────────────────────────────────────────────────────────────────
# The list itself is NOT here. It is one shared list in checklists.db (source
# `base:trip:grocery`, see trips/grocery_base.py), and a trip keeps only its ticks,
# in packing_ticks keyed by that list's id, the same way the packing tab works.
#
# The WHEN is not stored either, and never was a datetime: which side of check-in
# the run falls on is derived on every render from the outbound leg's arrival and
# the booked stay's check-in (trips.js groceryRun). A stored answer goes stale the
# moment either end moves, and nothing on screen would say so.

# ── Packing ticks ─────────────────────────────────────────────────────────────
# Per-trip state over /checklists' contents. See the packing_ticks CREATE in
# db_schema.create().


def packing_ticks(trip_id: int) -> set[tuple[int, int]]:
    """Every (list_id, item_id) this trip has packed."""
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT list_id, item_id FROM packing_ticks WHERE trip_id=?", (trip_id,)
        ).fetchall()
    return {(r["list_id"], r["item_id"]) for r in rows}


def set_packing_tick(trip_id: int, list_id: int, item_id: int, on: bool) -> None:
    with db._conn() as conn:
        if on:
            conn.execute(
                "INSERT OR IGNORE INTO packing_ticks (trip_id, list_id, item_id) VALUES (?,?,?)",
                (trip_id, list_id, item_id))
        else:
            conn.execute(
                "DELETE FROM packing_ticks WHERE trip_id=? AND list_id=? AND item_id=?",
                (trip_id, list_id, item_id))


def clear_packing_ticks(trip_id: int, list_id: int | None = None) -> int:
    """Untick one list for this trip, or the whole board when list_id is None."""
    with db._conn() as conn:
        if list_id is None:
            cur = conn.execute("DELETE FROM packing_ticks WHERE trip_id=?", (trip_id,))
        else:
            cur = conn.execute(
                "DELETE FROM packing_ticks WHERE trip_id=? AND list_id=?", (trip_id, list_id))
    return cur.rowcount


def grocery_list() -> dict | None:
    """The one grocery list every trip shares, or None when checklists.db is not up.

    ponytail: the None is only ever a trips unit test that booted trips.db and
    nothing else. app.py inits checklists before the first request, so a live read
    always has it. Widen this to a hard error if that stops being true.
    """
    if db.checklists_db._db_path is None:
        return None
    return db.checklists_db.ensure_source_list(
        db.grocery_base.BASE_SOURCE, db.grocery_base.NAME,
        category=db.grocery_base.BASE_CATEGORY, description=db.grocery_base.BLURB)


# ── Activities ────────────────────────────────────────────────────────────────


def add_activity(trip_id, data):
    return db._add("activities", trip_id, data, db._ACTIVITY_FIELDS)


def update_activity(trip_id, aid, data):
    return db._update("activities", aid, trip_id, data, db._ACTIVITY_FIELDS)


def delete_activity(trip_id, aid):
    return db._delete("activities", aid, trip_id)


# ── The departure every day needs ─────────────────────────────────────────────
# You are never at the first stop at the moment it starts, and the board held both
# halves of that sum — the house's coordinates and the stop's start time — while
# still leaving the subtraction to whoever read it, every morning. That is the one
# piece of arithmetic you get wrong on the day it costs you the trailhead.
#
# So each qualifying day gets a real activity row named "Leave home base", with a
# real time on it. A row and not a computed overlay, deliberately: it is a normal
# event you can retime, drag, delete or read on your phone, it survives the page
# that drew it, and because it is a scheduled activity the existing Google
# Calendar push carries it out to the phone with everything else. A derived block
# did none of that.
#
# Written once and then left alone. The seeded time is a starting answer, not a
# standing claim — the moment you retime it, that is the time, and nothing here
# recomputes over the top of it.
#
# `DEPARTURE_NAME`, `DEPARTURE_BUFFER_MIN` and the tuning constants
# (`_SAME_PLACE_MI`, `_ROAD_FACTOR`, `_DRIVE_FLOOR`, `_STAY_DECIDED`) all live on
# the facade — Rule 1 — and are reached here as `db.<name>`.


def _haversine_mi(a_lat, a_lng, b_lat, b_lng) -> float | None:
    if None in (a_lat, a_lng, b_lat, b_lng):
        return None
    import math
    to_r = math.pi / 180
    d_lat, d_lng = (b_lat - a_lat) * to_r, (b_lng - a_lng) * to_r
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(a_lat * to_r) * math.cos(b_lat * to_r) * math.sin(d_lng / 2) ** 2)
    return 3958.8 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _drive_min(mi: float) -> int:
    return max(db._DRIVE_FLOOR, round(mi * db._ROAD_FACTOR / 5) * 5)


def parse_clock(s) -> int | None:
    """"6:30 AM" | "22:30" -> minutes since midnight. Mirrors TripTime.parseClock."""
    if s is None:
        return None
    t = str(s).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$", t, re.I)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        if not 1 <= h <= 12 or mm > 59:
            return None
        h = 0 if h == 12 else h
        return h * 60 + mm + (720 if m.group(3).lower() == "p" else 0)
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    return None if h > 23 or mm > 59 else h * 60 + mm


def _fmt_clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _stay_window(stay: dict) -> tuple[str, int | None, str, int | None]:
    """(check-in date, check-in clock, check-out date, check-out clock)."""
    def split(stamp):
        parts = str(stamp or "").strip().split(" ", 1)
        date = parts[0] if len(parts[0]) == 10 else ""
        return date, (parse_clock(parts[1]) if len(parts) > 1 else None)
    ci, ci_min = split(stay.get("check_in"))
    co, co_min = split(stay.get("check_out"))
    return ci, ci_min, co, co_min


def _eligible_activities_by_day(acts: list[dict]) -> dict[str, list[dict]]:
    """Scheduled, timed, geolocated non-departure activities, grouped by day."""
    by_day: dict[str, list[dict]] = {}
    for a in acts:
        day = a.get("scheduled_date")
        if (a.get("status") != "scheduled" or not day or a.get("name") == db.DEPARTURE_NAME
                or a.get("lat") is None or a.get("lng") is None):
            continue
        if parse_clock(a.get("scheduled_time")) is None:
            continue                   # no start time, so no time to leave by
        by_day.setdefault(day, []).append(a)
    return by_day


def _clock_of(a: dict) -> int:
    """`parse_clock` on an activity already filtered by `_eligible_activities_by_day`,
    so this can never actually be None — the assert is for pyright, not runtime."""
    c = parse_clock(a["scheduled_time"])
    assert c is not None
    return c


def _departure_payload(stay: dict, day: str, rows: list[dict],
                        ci: str, ci_min: int | None, co: str) -> dict | None:
    """The "Leave home base" activity payload for one day, or None if this day
    doesn't warrant one (outside the stay, too close to walk, or too early)."""
    if ci and day < ci:
        return None
    if co and day > co:
        return None
    first = min(rows, key=_clock_of)
    start = _clock_of(first)
    mi = _haversine_mi(stay["lat"], stay["lng"], first["lat"], first["lng"])
    if mi is None or mi < db._SAME_PLACE_MI:
        return None
    drive = _drive_min(mi)
    dep = start - drive - db.DEPARTURE_BUFFER_MIN
    # A departure before midnight belongs to the day before, and on the
    # morning you check in you have not arrived yet.
    if dep <= 0 or (ci and day == ci and ci_min is not None and dep < ci_min):
        return None
    return {
        "name": db.DEPARTURE_NAME,
        "status": "scheduled",
        "scheduled_date": day,
        "scheduled_time": _fmt_clock(dep),
        "scheduled_time_end": _fmt_clock(dep),     # an instant: end == start
        "location": stay.get("address") or stay.get("name") or "",
        "lat": stay["lat"], "lng": stay["lng"],
        "cost": 0,
        "tags": db._json.dumps(["logistics"]),
        "notes": (f"Seeded from {first.get('name') or 'the first stop'} at "
                  f"{first.get('scheduled_time')}: ~{drive} min drive plus a "
                  f"{db.DEPARTURE_BUFFER_MIN} min buffer. Retime it and it stays "
                  f"where you put it."),
    }


def ensure_departures(trip_id: int) -> list[dict]:
    """Give every day that leaves the house a "Leave home base" event.

    Returns only the rows it created. A day that already has one is left exactly
    as it is — including its time, which is the whole point of storing it.

    ponytail: activities anchor the day, transportation does not. A shuttle
      leaving from the house already IS the departure; one leaving from anywhere
      else would want its own, and can have it the day a trip actually has one.
    """
    trip = db.get_full_trip(trip_id)
    if not trip:
        return []
    stay = next((h for h in trip.get("housing", [])
                 if h.get("status") in db._STAY_DECIDED
                 and h.get("lat") is not None and h.get("lng") is not None), None)
    if not stay:
        return []                      # no settled stay, nothing to leave from
    ci, ci_min, co, _ = _stay_window(stay)

    acts = trip.get("activities", [])
    have = {a.get("scheduled_date") for a in acts if a.get("name") == db.DEPARTURE_NAME}
    by_day = _eligible_activities_by_day(acts)

    made = []
    for day, rows in sorted(by_day.items()):
        if day in have:
            continue
        payload = _departure_payload(stay, day, rows, ci, ci_min, co)
        if payload is None:
            continue
        made.append(add_activity(trip_id, payload))
    return made


def get_activity(activity_id: int, trip_id: int) -> dict | None:
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM activities WHERE id=? AND trip_id=?", (activity_id, trip_id)
        ).fetchone()
    return db._row(row) if row else None
