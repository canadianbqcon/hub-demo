"""Trips data layer for the Hub module — the facade.

Ported from the legacy 5001 ``dashboard/db.py``. Reads/writes the shared
``data/trips.db`` (the same file the 5001 app used — no duplication, no
migration). The 5001 ``config.EXPOSED`` read-only guard is intentionally
dropped: the Hub stays editable when exposed (see hub/app.py).

Split by domain 2026-09-24 (Task 2 of
docs/archive/plans/2026-09-24-trips-split-complexity.md; was 1,950 lines).
This file is the facade: it owns `_db_path`, `_conn`, `init`, and every
module-level constant and import the sections below need, then re-exports
every moved function by explicit name. Every import/constant that looks
unused here is used through `db.<name>` from `db_schema.py`, `db_trips.py`,
`db_items.py`, `db_members.py`, `db_guests.py` and `db_prefs.py` — the F401
noqas mark that on purpose (spec Rule 1: the facade owns every module-level
name so a test patching `trips.db.X` reaches the code that actually runs).
"""

from __future__ import annotations

import json as _json  # noqa: F401 - reached as db._json by db_items/db_prefs
import logging
from pathlib import Path
from typing import Any  # noqa: F401 - kept for parity with the pre-split manifest

from checklists import db as checklists_db  # noqa: F401 - reached as db.checklists_db
from sqlite_helpers import (  # noqa: F401 - _row/_row_strict/_rows reached as db.<name>
    connect as sqlite_connect,
    row as _row,
    row_strict as _row_strict,
    rows as _rows,
)
from . import grocery_base, place_photos  # noqa: F401 - reached as db.grocery_base/db.place_photos

logger = logging.getLogger(__name__)

_db_path: Path | None = None


def init(db_path: Path) -> None:
    """Record the DB path and run an idempotent schema bootstrap.

    The schema and migrations themselves live in db_schema.create() — this
    just owns the path and the connection they run on, since `_db_path` is the
    global tests patch directly (`trips_db._db_path = ...`).
    """
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        db_schema.create(conn)


def _conn():
    return sqlite_connect(_db_path, "trips.db")


# ── Ruled-out cleanup (db_trips._settle / _purge_ruled_out read these) ────────
_DECIDED = ("booked", "confirmed")
_RULED_OUT = ("rejected", "unavailable", "cancelled")

# ── Housing (db_items.add_housing etc. read this) ─────────────────────────────
_HOUSING_FIELDS = {
    "name", "address", "check_in", "check_out", "confirmation_code",
    "nightly_rate", "total_cost", "url", "notes", "status", "lat", "lng",
    # the comparison dimensions — see migration 004
    "guests", "bedrooms", "beds", "baths", "parking", "area", "rating", "reviews",
    # amenity flags — see migration 006. NULL = unchecked, 0 = absent, 1 = present.
    "hot_tub", "pool_table", "pool",
    # only a booked row fills these — see migration 009
    "host", "check_in_method", "house_rules", "checkout_tasks",
    "cancellation_deadline", "deposit",
    # what the stay is like once you're inside it — see migration 010
    "amenities", "wifi", "wifi_ssid", "wifi_pass",
    # award pricing, parallel to the cash columns — see migration 012.
    # NULL means this listing has no points price at all (an Airbnb never will).
    "points_nightly", "points_total", "points_program", "points_transfer",
    # which half of the form this row draws — see migration 014
    "stay_type",
    # the listing's own photos, one per line — see migration 017
    "photos",
    # what a hotel answers and a house never asks (migration 024). All TEXT:
    # each carries terms as well as a figure, and the terms decide things.
    "room_type", "loyalty", "incidental_hold", "resort_fee", "breakfast",
    "late_checkout",
    # who it divides between, and who fronted it — see migration 015
    "split_with", "paid_by",
    # this line's own points valuation, in cents per point — see migration 016
    "cents_per_point",
}

# ── Flights (db_items.add_flight etc.) ─────────────────────────────────────────
_FLIGHT_FIELDS = {
    "direction", "airline", "flight_num", "from_airport", "to_airport",
    "departure_time", "arrival_time", "confirmation", "cost", "notes",
    "status", "terminal_from", "terminal_to", "location", "passenger",
    # award pricing — see migration 012
    "points_total", "points_program", "points_transfer",
    "split_with", "paid_by",
    # see migration 016
    "cents_per_point",
}

# ── Transportation (db_items.add_transport etc.) ───────────────────────────────
_TRANSPORT_FIELDS = {
    "type", "description", "departure", "arrival", "cost", "notes",
    "status", "location", "url", "scheduled_date", "scheduled_time",
    "lat", "lng",
    # rental/turo rows only — a bus leaves these empty (migration 007)
    "pickup_time", "dropoff_time", "seats",
    # only a booked row fills this — see migration 011
    "confirmation",
    # award pricing — see migration 012
    "points_total", "points_program", "points_transfer",
    "split_with", "paid_by",
    # see migration 016
    "cents_per_point",
}

# ── Expenses (db_items.add_expense etc.) ────────────────────────────────────────
_EXPENSE_FIELDS = {"category", "description", "amount", "currency", "paid_by", "status", "split_with"}

# ── Activities (db_items.add_activity etc.) ─────────────────────────────────────
_ACTIVITY_FIELDS = {
    "name", "location", "description", "cost", "url", "notes", "status", "tags",
    "scheduled_date", "scheduled_time", "scheduled_time_end", "lat", "lng",
    "score", "score_p", "score_c", "true_score", "operating_days",
    "operating_hours", "decision_reason", "group_identity", "log_notes",
    "split_with",
}

# ── The departure every day needs (db_items.ensure_departures) ─────────────────
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

DEPARTURE_NAME = "Leave home base"

# 30 minutes covers two things at once, which is why it is not 15. Seven people
# getting out of a house is most of it. The rest is the drive estimate's own
# optimism: it is a straight line times a road factor tuned on city driving, so
# Arvada -> Estes Park quotes about 75 minutes for a drive that really takes 90.
# The buffer absorbs that rather than the trailhead parking absorbing it.
DEPARTURE_BUFFER_MIN = 30
# Leaving is an instant: you go at 10:15 or you don't. It is stored with its end
# equal to its start, which is how this board says "zero duration" — distinct from a
# NULL end, which means the duration is simply unknown and gets drawn as a guess.
# The axis draws a zero-length row as a rule at its minute, not a box, so it no
# longer needs a fake window to be readable. Earlier rounds gave it the drive's whole
# span (read as an hour and three quarters of commitment) and then a flat 30 minutes
# (read as a half-hour appointment); both were untrue about the same thing.
_SAME_PLACE_MI = 0.5      # the stop IS the house — nothing to leave for
# Mirrors driveMin() in trips/frontend/static/trips.js. Two copies because one is
# a browser file and one is not; test_trips_departures.py reads the JS and pins
# them equal, so a change to either side fails rather than drifts.
_ROAD_FACTOR, _DRIVE_FLOOR = 1.75, 10
_STAY_DECIDED = _DECIDED + ("paid",)

# ── Members (db_members.add_member etc.) ────────────────────────────────────────
_MEMBER_FIELDS = {"name", "email", "notes", "contact_slug",
                  "card_header", "card_shimmer", "card_border"}
_CARD_SLOTS = ("card_header", "card_shimmer", "card_border")

# ── Guest codes (the public mirror's gate — db_guests.py) ──────────────────────
# Read by port 5003 to decide who gets in and what they see; written by Hub when
# Sam approves or denies. Everything here is scoped by contact_slug, which is
# the person identity `members` already carries.

NAME_KEY = "name:"  # prefix marking a guest key that is a crew name, not a wiki slug

# The identity a guest types about themselves. `name` is not in here: it is
# always derived from first + last, so the display name cannot drift away from
# the parts it is made of.
# address is account-only: it rides with phone and email, and nothing on the
# shared board prints it — a crew card shows a person, not their doorstep.
GUEST_FIELDS = ("first_name", "last_name", "phone", "email", "address")

# A four-digit code is 10,000 entries, which is small enough that the only honest
# defence is a budget on guesses rather than a delay between them. So wrong codes
# accumulate into strikes, each strike shuts the keypad for twice as long as the
# last, and the fifth does not reopen on a timer at all — it waits for Sam.
#
# That caps an attacker at roughly 150 tries before a human is in the loop: a 1.5%
# chance against the space, and a loud one, because the access panel shows the
# freeze. Members pay nothing for it. A guest already holding a session never
# posts to the keypad, so a freeze can only delay a NEW unlock, and honest typing
# does not reach ten wrong codes inside one window.
_WINDOW_FAILS, _WINDOW_SECONDS = 10, 900   # 10 wrong codes in 15 min fills a window
_FREEZE_BASE_SECONDS = 900                 # first strike: 15 min, then 30, 60, 120
_HARD_STOP_STRIKE = 5                      # the fifth waits for Sam, not a clock
_STRIKE_DECAY_SECONDS = 86400              # a quiet day forgives the escalation
_HARD_STOP_UNTIL = "9999-12-31 00:00:00"


# ── Sections, imported last (Rule 3: nothing above this line evaluates them) ──
from . import db_schema  # noqa: E402 - used by init() above
from .db_schema import create  # noqa: E402,F401 - explicit re-export, Rule 4
from .db_trips import (  # noqa: E402,F401 - explicit re-export, Rule 4
    _add,
    _airports_for,
    _attach_homes,
    _delete,
    _purge_ruled_out,
    _settle,
    _settled_debts,
    _update,
    airports_for,
    create_trip,
    delete_trip,
    get_full_trip,
    get_trip,
    list_trips,
    list_trips_summary,
    set_activity_cal_event_id,
    set_trip_cal_event_id,
    set_trip_cal_status,
    trip_airport_codes,
    trip_tz,
    trip_count,
    update_trip,
    upsert_airport,
    upsert_opinion,
)
from .db_items import (  # noqa: E402,F401 - explicit re-export, Rule 4
    _clock_of,
    _departure_payload,
    _drive_min,
    _eligible_activities_by_day,
    _fmt_clock,
    _haversine_mi,
    _stay_window,
    add_activity,
    add_expense,
    add_flight,
    add_housing,
    add_transport,
    clear_packing_ticks,
    delete_activity,
    delete_expense,
    delete_flight,
    delete_housing,
    delete_transport,
    ensure_departures,
    get_activity,
    grocery_list,
    packing_ticks,
    parse_clock,
    set_packing_tick,
    update_activity,
    update_expense,
    update_flight,
    update_housing,
    update_transport,
)
from .db_members import (  # noqa: E402,F401 - explicit re-export, Rule 4
    _key_where,
    add_member,
    delete_member,
    member_key,
    roster,
    trip_members,
    update_member,
)
from .db_guests import (  # noqa: E402,F401 - explicit re-export, Rule 4
    _stats_row,
    approve_guest_code,
    card_look,
    clear_gate_freeze,
    deny_guest_code,
    gate_frozen_until,
    gate_stats,
    geocode_home,
    guest_code_by_code,
    guest_code_by_id,
    guest_display_name,
    list_guest_codes,
    pending_guest_code_count,
    record_gate_failure,
    request_guest_code,
    set_card_look,
    set_guest_code,
    set_guest_fields,
    set_guest_home,
    touch_guest_code,
    trips_by_key,
    trips_for_slug,
)
from .db_prefs import (  # noqa: E402,F401 - explicit re-export, Rule 4
    claim_response,
    prefs_for_refs,
    save_form_responses,
    unmatched_responses,
)
