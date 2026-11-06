"""Trip CRUD, full-trip assembly, generic sub-resource row helpers, ruled-out
shortlist cleanup, airport cache and calendar event-id setters.

Split out of trips/db.py (Task 2). The facade (trips/db.py) owns `_conn`,
`_db_path` and every constant these functions read (`_DECIDED`, `_RULED_OUT`,
`grocery_base`, `place_photos`, the `_row*`/`_rows` converters); reached here
as `db.<name>` at call time so a test that patches the facade still lands on
the code these functions run. See the design spec's Rule 2.
"""

from __future__ import annotations

import json
from typing import Any

from . import db


def _settled_debts(trip_id: int) -> list[str]:
    """`owed.src` keys of this trip's debts the owed tab marks paid.

    The settle-up card only knew what was fronted, never what was paid back, so
    it kept billing Aria $760.00 for El Salvador after her $700 Venmo cleared
    both lines (2026-11-03). The cost tab drops each of these shares from the
    settlement. owed.db sits beside trips.db; a missing one means nothing settled.
    """
    import sqlite3
    from contextlib import closing

    if db._db_path is None:
        return []
    p = db._db_path.parent / "owed.db"
    if not p.exists():
        return []
    with closing(sqlite3.connect(f"file:{p}?mode=ro", uri=True)) as c:
        return [r[0] for r in c.execute(
            "SELECT src FROM owed WHERE status='paid' AND src LIKE ?",
            (f"trip:{trip_id}/%",),
        )]


def list_trips() -> list[dict]:
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM trips ORDER BY start_date ASC").fetchall()
    return db._rows(rows)


def list_trips_summary() -> list[dict]:
    """Every trip plus the counts the landing page renders, in two queries.

    Deliberately does NOT compute "next up" in SQL. ``activities.scheduled_time``
    holds mixed formats ("11:00 AM", "22:30", "08:00", ""), which SQLite cannot
    order chronologically — ``ORDER BY scheduled_time`` falls back to a string
    sort and picks "10:30 PM" over "11:00 AM" on the same day. So the raw
    scheduled rows ship to the client and triptime.js picks the earliest. One
    parser, one source of truth. (Caught in the 2026-08-06 adversarial review of
    docs/archive/specs/2026-08-06-trip-planner-revamp-design.md.)
    """
    with db._conn() as conn:
        trips = db._rows(conn.execute("""
            SELECT t.*,
              (SELECT COUNT(*) FROM activities a WHERE a.trip_id=t.id AND a.status='scheduled')            AS n_scheduled,
              (SELECT COUNT(*) FROM activities a WHERE a.trip_id=t.id AND a.status NOT IN ('scheduled','skip')) AS n_ideas,
              (SELECT COUNT(*) FROM members  m WHERE m.trip_id=t.id)                                        AS n_crew,
              (SELECT COALESCE(SUM(e.amount), 0) FROM expenses e WHERE e.trip_id=t.id)                      AS budget_total,
              (SELECT COUNT(*) FROM housing h WHERE h.trip_id=t.id AND h.status IN ('booked','confirmed'))  AS n_housing_booked,
              (SELECT COUNT(*) FROM housing h WHERE h.trip_id=t.id)                                         AS n_housing,
              (SELECT COUNT(*) FROM flights f WHERE f.trip_id=t.id AND f.status IN ('booked','confirmed'))  AS n_flights_booked,
              (SELECT COUNT(*) FROM flights f WHERE f.trip_id=t.id)                                         AS n_flights
            FROM trips t ORDER BY t.start_date ASC
        """).fetchall())
        sched = db._rows(conn.execute(
            "SELECT trip_id, name, scheduled_date, scheduled_time FROM activities"
            " WHERE status='scheduled' AND scheduled_date <> ''"
        ).fetchall())
        # The landing card's price runs the SAME cost model the trip page runs
        # (trips-cost.js), so the two pages can never disagree. That needs the
        # raw priced rows, not a SQL sum — `budget_total` above is SUM(expenses)
        # and is blind to the stay, the fares and the car, which is how Denver
        # showed no price at all while a $1,866 Airbnb sat booked.
        # Only the columns the model reads; a full SELECT * would ship every
        # note and confirmation code to a page that renders four numbers.
        # `paid_by` and `split_with` are on EVERY table here because the model's
        # per-person figure is "what does he pay at the end of the day", and that
        # is answered by who a row is FOR (split_with) and whose card it is on
        # (paid_by), not by a head count. Without them the landing card billed
        # him for a ticket he bought for another traveller — the trip page,
        # which selects *, did not, and the two pages disagreed by a whole fare.
        cost = {
            "housing": db._rows(conn.execute(
                "SELECT trip_id, total_cost, status, points_total, points_transfer, cents_per_point,"
                " paid_by, split_with FROM housing").fetchall()),
            "flights": db._rows(conn.execute(
                "SELECT trip_id, cost, status, direction, passenger, points_total, points_transfer,"
                " cents_per_point, paid_by, split_with FROM flights").fetchall()),
            "transportation": db._rows(conn.execute(
                "SELECT trip_id, cost, status, type, points_total, points_transfer, cents_per_point,"
                " paid_by, split_with FROM transportation").fetchall()),
            "expenses": db._rows(conn.execute(
                "SELECT trip_id, amount, status, category, paid_by, split_with FROM expenses").fetchall()),
            "members": db._rows(conn.execute(
                "SELECT trip_id, id, name, contact_slug FROM members").fetchall()),
        }
    by_trip: dict[int, list[dict]] = {}
    for r in sched:
        by_trip.setdefault(r["trip_id"], []).append(
            {"name": r["name"], "scheduled_date": r["scheduled_date"], "scheduled_time": r["scheduled_time"]}
        )
    by_table: dict[str, dict[int, list[dict]]] = {}
    for table, rows in cost.items():
        bucket: dict[int, list[dict]] = {}
        for r in rows:
            bucket.setdefault(r["trip_id"], []).append(r)
        by_table[table] = bucket
    for t in trips:
        t["scheduled"] = by_trip.get(t["id"], [])
        for table, bucket in by_table.items():
            t[table] = bucket.get(t["id"], [])
    return trips


def get_trip(trip_id: int) -> dict | None:
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    return db._row(row) if row else None


def create_trip(data: dict) -> dict:
    with db._conn() as conn:
        cur = conn.execute(
            "INSERT INTO trips (name, destination, start_date, end_date, cal_event_id, notes)"
            " VALUES (:name, :destination, :start_date, :end_date, :cal_event_id, :notes)",
            {
                "name": data.get("name", ""),
                "destination": data.get("destination", ""),
                "start_date": data.get("start_date", ""),
                "end_date": data.get("end_date", ""),
                "cal_event_id": data.get("cal_event_id"),
                "notes": data.get("notes", ""),
            },
        )
        row = conn.execute("SELECT * FROM trips WHERE id=?", (cur.lastrowid,)).fetchone()
    return db._row_strict(row)


def update_trip(trip_id: int, data: dict) -> dict | None:
    allowed = {"name", "destination", "start_date", "end_date", "notes", "trip_interests",
               "grocery_extras"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return get_trip(trip_id)
    sets = ", ".join(f"{k}=?" for k in updates)
    with db._conn() as conn:
        conn.execute(f"UPDATE trips SET {sets} WHERE id=?", (*updates.values(), trip_id))
        row = conn.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    return db._row(row) if row else None


def delete_trip(trip_id: int) -> bool:
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM trips WHERE id=?", (trip_id,))
    # Grocery ticks live in packing_ticks and cascade with the trip; the shared
    # list itself belongs to every trip and stays.
    return cur.rowcount > 0


def get_full_trip(trip_id: int, with_home: bool = False) -> dict | None:
    """The whole trip in one payload.

    `with_home` attaches each member's home address and its geocode, joined off
    guest_codes by contact_slug, for the day-of ride chain — one car collecting
    the crew furthest-first instead of four cars to the same terminal.

    The mirror asks for it too, so the crew get the chain on their own phones and
    not only Sam on Hub — which is the point of a shared morning ride. That is
    a deliberate widening of guest_codes.address, which was account-only before
    (see GUEST_FIELDS), decided by Sam on 2026-08-28. The scope is still
    narrow: a guest only ever loads trips they are ON, so an address reaches
    exactly the people that person is sharing a car with.

    It still defaults to FALSE and every caller has to ask. Every other consumer of
    this payload — the landing card, the cost model, the calendar push — has no
    business carrying an address, and a default of True would put one in all of
    them the day somebody adds a route.
    """
    # One connection for the whole read. It used to take three (get_trip, this
    # block, airports_for) and on /mnt/c an open costs ~20 ms against queries
    # measured in tenths of one.
    with db._conn() as conn:
        trip = db._row(conn.execute(
            "SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone())
        if not trip:
            return None
        # A hotel row stores a pointer to Google's photos rather than URLs, because
        # Google's links expire and may not be cached — see place_photos.
        trip["housing"] = [db.place_photos.expand(h) for h in db._rows(
            conn.execute(
                "SELECT * FROM housing WHERE trip_id=? ORDER BY id", (trip_id,)
            ).fetchall()
        )]
        trip["flights"] = db._rows(
            conn.execute(
                "SELECT * FROM flights WHERE trip_id=? ORDER BY departure_time", (trip_id,)
            ).fetchall()
        )
        trip["transportation"] = db._rows(
            conn.execute(
                "SELECT * FROM transportation WHERE trip_id=? ORDER BY id", (trip_id,)
            ).fetchall()
        )
        trip["expenses"] = db._rows(
            conn.execute(
                "SELECT * FROM expenses WHERE trip_id=? ORDER BY id", (trip_id,)
            ).fetchall()
        )
        trip["activities"] = db._rows(
            conn.execute(
                "SELECT * FROM activities WHERE trip_id=? ORDER BY status DESC, id",
                (trip_id,),
            ).fetchall()
        )
        trip["members"] = db._rows(
            conn.execute(
                "SELECT * FROM members WHERE trip_id=? ORDER BY id", (trip_id,)
            ).fetchall()
        )
        trip["settled_debts"] = _settled_debts(trip_id)
        trip["flight_research"] = [
            {**r, **{k: json.loads(r[k] or "null") for k in ("query", "results", "errors")}}
            for r in db._rows(conn.execute(
                "SELECT * FROM flight_research WHERE trip_id=? ORDER BY searched_at DESC, id DESC",
                (trip_id,)).fetchall())
        ]
        opinion_rows = db._rows(
            conn.execute(
                "SELECT o.activity_id, o.member_id, o.rating FROM activity_opinions o"
                " JOIN activities a ON o.activity_id = a.id WHERE a.trip_id=?",
                (trip_id,),
            ).fetchall()
        )
        ops: dict[int, dict[str, Any]] = {}
        for r in opinion_rows:
            ops.setdefault(r["activity_id"], {})[str(r["member_id"])] = r["rating"]
        for act in trip["activities"]:
            act["opinions"] = ops.get(act["id"], {})
        # Every IATA this trip touches, with coordinates where the cache has them.
        # Shipped as a lookup rather than folded onto each flight row because both
        # ends of a leg need it and the same airport recurs across legs and trips.
        trip["airports"] = _airports_for(conn, trip_airport_codes(trip))
        if with_home:
            _attach_homes(conn, trip)
    # Read OUTSIDE the trips connection: the list lives in checklists.db and this
    # one `with` block is scoped to trips.db. Unbought first, then hand order: the
    # board is read while walking a store, so what is left has to be at the top
    # without a filter. Covered items sink with the bought ones.
    cl = db.grocery_list()
    shape = trip.get("grocery_extras") or "visit"
    items = db.grocery_base.for_shape((cl or {}).get("items", []), shape)
    stay = db.grocery_base.booked_stay(trip) or {}
    _keep, covered = db.grocery_base.trim(items, stay.get("amenities", ""), stay.get("stay_type", ""))
    ticks = db.packing_ticks(trip_id)
    cl_id = (cl or {}).get("id")
    for i in items:
        i["checked"] = 1 if (cl_id, i["id"]) in ticks else 0
        i["covered"] = 1 if i["text"] in covered else 0
    trip["grocery"] = sorted(
        items, key=lambda i: (i["checked"] or i["covered"], i["sort_order"], i["id"]))
    trip["grocery_stay"] = stay.get("name", "")
    trip["grocery_list_id"] = cl_id
    return trip


def _attach_homes(conn, trip: dict) -> None:
    """Put `home` on every member whose account carries an address.

    The join is contact_slug — the same key that binds a roster row to a guest
    account everywhere else — so a member nobody has approved a code for simply
    has no home, which is the normal case rather than an error. A member with an
    address but no coordinates yet gets the string alone: the card can print it
    and the geocode pass fills the point in later.
    """
    slugs = [s for s in ((m.get("contact_slug") or "").strip() for m in trip.get("members", [])) if s]
    if not slugs:
        return
    rows = conn.execute(
        "SELECT contact_slug, address, home_lat, home_lng FROM guest_codes"
        " WHERE status='approved' AND contact_slug IN (%s)" % ",".join("?" * len(slugs)),
        slugs,
    ).fetchall()
    by_slug = {r["contact_slug"]: r for r in rows if (r["address"] or "").strip()}
    for m in trip.get("members", []):
        r = by_slug.get((m.get("contact_slug") or "").strip())
        if r:
            m["home"] = {"address": r["address"], "lat": r["home_lat"], "lng": r["home_lng"]}


def trip_airport_codes(trip: dict) -> list[str]:
    """Distinct IATA codes on a trip's flights, both ends of every leg."""
    codes = []
    for f in trip.get("flights", []):
        for key in ("from_airport", "to_airport"):
            code = (f.get(key) or "").strip().upper()
            if code and code not in codes:
                codes.append(code)
    return codes


def trip_tz(trip_id: int) -> str:
    """The destination's IANA zone: where his own outbound flight lands, else any
    traveller's. "" when no outbound flight or no cached zone, and the caller then
    keeps the all-day calendar body."""
    with db._conn() as conn:
        row = conn.execute(
            "SELECT a.tz FROM flights f JOIN airports a ON a.iata = UPPER(TRIM(f.to_airport))"
            " WHERE f.trip_id=? AND f.direction='outbound' AND a.tz != ''"
            " ORDER BY (COALESCE(f.passenger,'') != ''), f.id LIMIT 1",
            (trip_id,),
        ).fetchone()
    return row[0] if row else ""


def _airports_for(conn, codes: list[str]) -> dict[str, dict]:
    """The body of `airports_for`, on a caller's connection. Split out so
    `get_full_trip` can read airports inside the connection it already holds —
    on /mnt/c an extra open costs ~20 ms, several times the query itself."""
    if not codes:
        return {}
    rows = conn.execute(
        "SELECT iata, name, lat, lng, tz FROM airports WHERE iata IN (%s)"
        % ",".join("?" * len(codes)),
        codes,
    ).fetchall()
    return {r["iata"]: {"name": r["name"], "lat": r["lat"], "lng": r["lng"], "tz": r["tz"] or ""}
            for r in rows}


def airports_for(codes: list[str]) -> dict[str, dict]:
    """{IATA: {name, lat, lng}} for the codes we have cached. Unresolved codes
    are simply absent — the caller decides whether to geocode them."""
    if not codes:
        return {}
    with db._conn() as conn:
        return _airports_for(conn, codes)


def upsert_airport(iata: str, lat: float, lng: float, name: str = "", tz: str = "") -> None:
    """Cache one airport. An empty `tz` LEAVES a zone already on the row: a
    re-geocode is about coordinates, and the zone lookup is a separate call that
    is allowed to fail without wiping the answer from the last time it didn't."""
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO airports (iata, name, lat, lng, tz, resolved_at)"
            " VALUES (?,?,?,?,?, datetime('now'))"
            " ON CONFLICT(iata) DO UPDATE SET"
            " name=excluded.name, lat=excluded.lat, lng=excluded.lng,"
            " tz=CASE WHEN excluded.tz = '' THEN airports.tz ELSE excluded.tz END,"
            " resolved_at=excluded.resolved_at",
            (iata.strip().upper(), name, lat, lng, (tz or "").strip()),
        )


def upsert_opinion(activity_id: int, member_id: int, rating) -> None:
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO activity_opinions (activity_id, member_id, rating) VALUES (?, ?, ?)"
            " ON CONFLICT(activity_id, member_id) DO UPDATE SET rating=excluded.rating",
            (activity_id, member_id, rating),
        )


# ── Generic sub-resource helpers ──────────────────────────────────────────────


def _add(table: str, trip_id: int, data: dict, allowed_fields: set) -> dict:
    fields = {k: v for k, v in data.items() if k in allowed_fields}
    fields["trip_id"] = trip_id
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{k}" for k in fields)
    with db._conn() as conn:
        cur = conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", fields
        )
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id=?", (cur.lastrowid,)
        ).fetchone()
    return db._row_strict(row)


def _update(table: str, row_id: int, trip_id: int, data: dict, allowed_fields: set) -> dict | None:
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    if not updates:
        with db._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE id=? AND trip_id=?", (row_id, trip_id)
            ).fetchone()
        return db._row(row) if row else None
    sets = ", ".join(f"{k}=?" for k in updates)
    with db._conn() as conn:
        conn.execute(
            f"UPDATE {table} SET {sets} WHERE id=? AND trip_id=?",
            (*updates.values(), row_id, trip_id),
        )
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id=? AND trip_id=?", (row_id, trip_id)
        ).fetchone()
    return db._row(row) if row else None


def _delete(table: str, row_id: int, trip_id: int) -> bool:
    with db._conn() as conn:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE id=? AND trip_id=?", (row_id, trip_id)
        )
    return cur.rowcount > 0


# ── Ruled-out cleanup ─────────────────────────────────────────────────────────
# A shortlist is only worth keeping while the choice is open. Once the flight is
# booked or the stay is confirmed, the options that were ruled out stop being
# evidence and become clutter — six rejected Denver roundtrips sat under a booked
# ticket with nothing left to decide.
#
# Two deliberate limits. It fires only when something is actually DECIDED, so a
# search that turned up four dead listings and no booking keeps all four. And it
# only removes rows already marked ruled-out — a `considering` sibling is still a
# live alternative, and is never touched. Trip-scoped rather than per-direction:
# a rejected return is ruled out whichever leg got decided, and a roundtrip fare
# competes with an outbound/return pair for the same decision.
#
# This is a hard delete with no undo. The decided row's own notes and log/log.md
# carry the outcome; what is lost is the shortlist behind it.
# (`_DECIDED` / `_RULED_OUT` are facade constants, reached below as db._DECIDED /
# db._RULED_OUT — Rule 1 keeps every module-level constant on the facade.)


def _purge_ruled_out(table: str, trip_id: int) -> int:
    """Drop every ruled-out row in `table` for this trip. Returns how many went."""
    marks = ", ".join("?" for _ in db._RULED_OUT)
    with db._conn() as conn:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE trip_id=? AND status IN ({marks})",
            (trip_id, *db._RULED_OUT),
        )
    return cur.rowcount


def _settle(table: str, trip_id: int, row: dict | None) -> dict | None:
    """After a write, purge the losers if that write is what decided the choice."""
    if row and row.get("status") in db._DECIDED:
        purged = _purge_ruled_out(table, trip_id)
        if purged:
            row = {**row, "purged": purged}
    return row


# ── Calendar event-id setters ─────────────────────────────────────────────────


def set_trip_cal_event_id(trip_id: int, cal_event_id: str | None) -> None:
    with db._conn() as conn:
        conn.execute("UPDATE trips SET cal_event_id=? WHERE id=?", (cal_event_id, trip_id))


def set_trip_cal_status(trip_id: int, status: str) -> None:
    """Flag a trip's calendar-sync state. '' = healthy/unknown, 'deleted' = the
    Google Calendar event was removed outside the dashboard. Set by the daily
    reconcile; never a user-facing edit field."""
    with db._conn() as conn:
        conn.execute("UPDATE trips SET cal_status=? WHERE id=?", (status, trip_id))


def set_activity_cal_event_id(activity_id: int, cal_event_id: str | None) -> None:
    with db._conn() as conn:
        conn.execute(
            "UPDATE activities SET cal_event_id=? WHERE id=?", (cal_event_id, activity_id)
        )


def trip_count() -> int:
    with db._conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
