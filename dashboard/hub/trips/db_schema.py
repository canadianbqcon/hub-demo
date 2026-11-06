"""Trip DB schema and migrations.

Split out of trips/db.py (Task 2 of
docs/archive/plans/2026-09-24-trips-split-complexity.md). Owns nothing at
module scope: the facade (trips/db.py) holds `_db_path`, `logger` and every
constant, and calls `create(conn)` once from `db.init()`. This file only
defines that function.
"""

from __future__ import annotations

from . import db


def create(conn) -> None:
    """Run the idempotent schema bootstrap on `conn`.

    The vault's trips.db is already fully populated and migrated by the 5001
    app, so the CREATE/ALTER pass below is a no-op there (every ADD COLUMN that
    already exists raises and is swallowed). It only matters on a fresh machine
    where the Hub is the first to touch the file.

    Order matters and used to be wrong: the ADD COLUMN pass ran BEFORE the
    CREATE TABLE pass, so on a fresh file every ALTER hit a table that did not
    exist yet, raised, and was swallowed by the same handler that legitimately
    swallows "column already exists". A new machine got the 001-era schema with
    every later column missing. Invisible on Sam's populated DB, and the
    reason `transportation.location` did not exist under a fresh test fixture.
    """
    conn.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS trips (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            destination TEXT DEFAULT '',
            start_date  TEXT DEFAULT '',
            end_date    TEXT DEFAULT '',
            cal_event_id TEXT UNIQUE,
            notes       TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS housing (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id          INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            name             TEXT DEFAULT '',
            address          TEXT DEFAULT '',
            check_in         TEXT DEFAULT '',
            check_out        TEXT DEFAULT '',
            confirmation_code TEXT DEFAULT '',
            nightly_rate     REAL,
            total_cost       REAL,
            url              TEXT DEFAULT '',
            notes            TEXT DEFAULT '',
            status           TEXT DEFAULT 'considering'
        );

        CREATE TABLE IF NOT EXISTS flights (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id        INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            direction      TEXT DEFAULT 'outbound',
            airline        TEXT DEFAULT '',
            flight_num     TEXT DEFAULT '',
            from_airport   TEXT DEFAULT '',
            to_airport     TEXT DEFAULT '',
            departure_time TEXT DEFAULT '',
            arrival_time   TEXT DEFAULT '',
            confirmation   TEXT DEFAULT '',
            cost           REAL,
            notes          TEXT DEFAULT '',
            status         TEXT DEFAULT 'booked'
        );

        CREATE TABLE IF NOT EXISTS transportation (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            type        TEXT DEFAULT 'other',
            description TEXT DEFAULT '',
            departure   TEXT DEFAULT '',
            arrival     TEXT DEFAULT '',
            cost        REAL,
            notes       TEXT DEFAULT '',
            status      TEXT DEFAULT 'considering'
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            category    TEXT DEFAULT 'misc',
            description TEXT DEFAULT '',
            amount      REAL DEFAULT 0,
            currency    TEXT DEFAULT 'USD',
            paid_by     TEXT DEFAULT '',
            status      TEXT DEFAULT 'estimated'
        );

        CREATE TABLE IF NOT EXISTS activities (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id        INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            name           TEXT NOT NULL,
            location       TEXT DEFAULT '',
            description    TEXT DEFAULT '',
            cost           REAL,
            url            TEXT DEFAULT '',
            notes          TEXT DEFAULT '',
            status         TEXT DEFAULT 'considering',
            tags           TEXT DEFAULT '',
            scheduled_date TEXT DEFAULT '',
            scheduled_time TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS members (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            name    TEXT NOT NULL,
            email   TEXT DEFAULT '',
            notes   TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS activity_opinions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            rating      INTEGER,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(activity_id, member_id)
        );

        /* Airport coordinates are a property of the airport, not of the
           flight — LGA is LGA on every trip — so they cache here by IATA
           instead of adding two columns to `flights` that would be
           re-geocoded per row. See migration 005. */
        CREATE TABLE IF NOT EXISTS airports (
            iata        TEXT PRIMARY KEY,
            name        TEXT DEFAULT '',
            lat         REAL,
            lng         REAL,
            /* IANA zone the flight stamps at this airport are written in.
               Stamps are local wall-clock at their own end, so anything
               that SUBTRACTS two of them needs both zones or it reports a
               transcontinental hop as a short hop. See migration 021. */
            tz          TEXT DEFAULT '',
            resolved_at TEXT DEFAULT ''
        );

        /* Guest access to the public mirror (trips/public_app.py, port 5003).
           A 4-digit code someone picks for themselves, which grants nothing
           until Sam approves it and links it to a person via
           contact_slug. The code then opens exactly that person's trips —
           `members` is the source of which ones. Codes are stored plain on
           purpose: a 4-digit space is 10,000 entries, so any hash of it is
           reversed instantly and buys nothing, while plain text lets Sam
           read someone their code back. See the design spec at
           docs/archive/specs/2026-08-14-trips-passcode-gate-design.md. */
        CREATE TABLE IF NOT EXISTS guest_codes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            /* `name` stays the display name and is derived from the two
               parts below, so every existing caller that prints a guest
               keeps working without knowing they were split. */
            name         TEXT NOT NULL,
            first_name   TEXT DEFAULT '',
            last_name    TEXT DEFAULT '',
            phone        TEXT DEFAULT '',
            email        TEXT DEFAULT '',
            address      TEXT DEFAULT '',
            code         TEXT NOT NULL,
            contact_slug TEXT DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            decided_at   TEXT DEFAULT '',
            last_seen    TEXT DEFAULT ''
        );

        /* Partial on purpose. Approved codes must be unique because the code
           alone identifies the guest at the keypad, but constraining pending
           rows too would turn the signup route into an oracle: submit every
           code from 0000 up and the collision errors report which ones are
           live. Pending and denied rows are therefore unconstrained, and the
           collision surfaces at Sam's approve click instead. */
        CREATE UNIQUE INDEX IF NOT EXISTS guest_codes_approved
            ON guest_codes(code) WHERE status = 'approved';

        /* An approved code with no contact_slug opens nothing — or, if the
           scoping lookup were ever written to fail open, everything. Making
           it unrepresentable is cheaper than trusting every future caller. */
        CREATE TRIGGER IF NOT EXISTS guest_codes_approved_needs_slug
        BEFORE UPDATE OF status ON guest_codes
        WHEN NEW.status = 'approved' AND COALESCE(NEW.contact_slug, '') = ''
        BEGIN SELECT RAISE(ABORT, 'approved guest code requires contact_slug'); END;

        /* Submitted Google Form responses, one row per response, never
           overwritten. Google Forms has no update-in-place, so "change your
           answers" means submitting again — history is what that produces,
           and keeping it is free. The newest row per (ref, kind) is the
           live answer; see prefs_for_refs.

           `ref` is db.member_key output, carried through the form in a
           prefilled question (trips/forms_intake.py). It is '' for the
           eleven responses submitted before that question existed, and for
           anyone who clears it — those surface as unmatched rather than
           being guessed at, because attaching one person's allergies to
           another is not a recoverable mistake. */
        CREATE TABLE IF NOT EXISTS member_prefs (
            kind         TEXT NOT NULL,
            response_id  TEXT NOT NULL,
            ref          TEXT NOT NULL DEFAULT '',
            name         TEXT NOT NULL DEFAULT '',
            submitted_at TEXT NOT NULL DEFAULT '',
            payload      TEXT NOT NULL DEFAULT '{}',
            synced_at    TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (kind, response_id)
        );

        CREATE INDEX IF NOT EXISTS member_prefs_ref
            ON member_prefs(ref, kind, submitted_at DESC);

        /* One row, ever. guest_codes.last_seen only ever moves for somebody
           who is already through the door, so on its own it leaves a run of
           failed attempts — which is what a break-in attempt looks like —
           completely invisible. */
        CREATE TABLE IF NOT EXISTS guest_gate_stats (
            id             INTEGER PRIMARY KEY CHECK (id = 1),
            fails          INTEGER NOT NULL DEFAULT 0,
            last_fail_at   TEXT DEFAULT '',
            /* The strike system — see record_gate_failure. Durable because the
               public unit runs Restart=always, and an in-memory counter hands
               an attacker a clean slate for the price of a crash. */
            strikes        INTEGER NOT NULL DEFAULT 0,
            window_fails   INTEGER NOT NULL DEFAULT 0,
            frozen_until   TEXT DEFAULT '',
            window_start   TEXT DEFAULT '',
            last_strike_at TEXT DEFAULT ''
        );

        /* Packing ticks belong to the TRIP, not to /checklists. The packing
           tab draws Sam's real lists straight out of checklists.db, but
           "packed" is a fact about one trip: the same Toiletries list gets
           packed again for the next one, and a tick written back to
           /checklists would carry across every trip at once and leave that
           board permanently half-ticked. So contents come from there and
           state lives here. An absent row means not packed, so a new trip
           starts clean with nothing to seed and nothing to reset. */
        CREATE TABLE IF NOT EXISTS packing_ticks (
            trip_id   INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            list_id   INTEGER NOT NULL,
            item_id   INTEGER NOT NULL,
            ticked_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (trip_id, list_id, item_id)
        );

        /* A guest's whole-trip form submission, held until Sam approves it
           in the Hub access panel. See migration 025 and trips/intake.py. */
        CREATE TABLE IF NOT EXISTS trip_intake (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id         INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            guest_key       TEXT NOT NULL,
            payload         TEXT NOT NULL DEFAULT '{}',
            diff            TEXT NOT NULL DEFAULT '{}',
            status          TEXT NOT NULL DEFAULT 'pending',
            submitted_at    TEXT NOT NULL DEFAULT (datetime('now')),
            decided_at      TEXT DEFAULT '',
            research_status TEXT NOT NULL DEFAULT '',
            apply_log       TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS trip_intake_guest
            ON trip_intake(guest_key, trip_id, status);

        /* One row per `flight-search.py --trip N` run: the top results, shown on
           the flights tab until Sam books his own flight (trigger below). */
        CREATE TABLE IF NOT EXISTS flight_research (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            searched_at TEXT NOT NULL DEFAULT (datetime('now')),
            query       TEXT NOT NULL DEFAULT '{}',
            results     TEXT NOT NULL DEFAULT '[]',
            errors      TEXT NOT NULL DEFAULT '[]'
        );
    """)
    conn.executescript("PRAGMA foreign_keys = ON;")
    for table, col, defval in [
        ("activities", "tags", "''"),
        ("activities", "scheduled_date", "''"),
        ("activities", "scheduled_time", "''"),
        ("activities", "scheduled_time_end", "''"),
        ("activities", "operating_days", "''"),
        ("activities", "operating_hours", "''"),
        ("activities", "decision_reason", "''"),
        ("activities", "group_identity", "''"),
        ("activities", "log_notes", "''"),
        ("activities", "cal_event_id", "''"),
        ("flights", "terminal_from", "''"),
        ("flights", "terminal_to", "''"),
        ("flights", "location", "''"),
        ("flights", "passenger", "''"),
        ("transportation", "location", "''"),
        ("transportation", "url", "''"),
        ("transportation", "scheduled_date", "''"),
        ("transportation", "scheduled_time", "''"),
        ("transportation", "pickup_time", "''"),
        ("transportation", "dropoff_time", "''"),
        ("members", "contact_slug", "''"),
        # The three cosmetic slots on a crew card, each unlocked by one of
        # the three things a member fills in. Empty = never picked, which
        # renders as that slot's plain default rather than as a gap.
        ("members", "card_header", "''"),
        ("members", "card_shimmer", "''"),
        ("members", "card_border", "''"),
        ("trips", "trip_interests", "''"),
        ("trips", "cal_status", "''"),
        ("trips", "wiki_slug", "''"),
        # Which grocery extras section a trip shows: '' (none), 'rave' or
        # 'snowboarding'. Picked by Sam on the grocery tab, never guessed.
        ("trips", "grocery_extras", "''"),
        ("housing", "amenities", "''"),
        ("housing", "area", "''"),
        ("housing", "cancellation_deadline", "''"),
        ("housing", "check_in_method", "''"),
        ("housing", "checkout_tasks", "''"),
        ("housing", "host", "''"),
        ("housing", "house_rules", "''"),
        ("housing", "parking", "''"),
        ("housing", "wifi", "''"),
        ("housing", "wifi_ssid", "''"),
        ("housing", "wifi_pass", "''"),
        ("housing", "points_program", "''"),
        ("housing", "stay_type", "''"),
        ("housing", "photos", "''"),
        # A new housing column lands in FOUR places, not two: the migration,
        # this bootstrap list (a fresh db.init() DB has to match the real one,
        # which test_trips_fresh_schema asserts), the _HOUSING_FIELDS write
        # allow-list below (miss it and the PATCH is dropped with a 200), and
        # the HOUSING_COLS mirror inside selfCheck() in trips.js, which reads
        # a column it has never heard of as a stray form field.
        # what a hotel answers and a house never asks (migration 024)
        ("housing", "room_type", "''"),
        ("housing", "loyalty", "''"),
        ("housing", "incidental_hold", "''"),
        ("housing", "resort_fee", "''"),
        ("housing", "breakfast", "''"),
        ("housing", "late_checkout", "''"),
        ("flights", "points_program", "''"),
        ("transportation", "confirmation", "''"),
        ("transportation", "points_program", "''"),
        # The gate's strike system. Durable on purpose: the counters used to
        # live in the public process's memory, and that unit runs with
        # Restart=always, so a crash — or anything that could cause one —
        # forgave every wrong code ever tried.
        ("guest_codes", "first_name", "''"),
        ("guest_codes", "last_name", "''"),
        ("guest_codes", "phone", "''"),
        ("guest_codes", "email", "''"),
        ("guest_codes", "address", "''"),
        ("guest_gate_stats", "frozen_until", "''"),
        ("guest_gate_stats", "window_start", "''"),
        ("guest_gate_stats", "last_strike_at", "''"),
        # Cost-split tagging — comma-separated members.id, empty = whole crew
        # (housing/transportation) or Sam alone (flights/expenses/activities).
        ("housing", "split_with", "''"),
        ("flights", "split_with", "''"),
        ("transportation", "split_with", "''"),
        ("expenses", "split_with", "''"),
        ("activities", "split_with", "''"),
        # Who fronted the money — one members.id, empty = unclaimed.
        # See migration 015; expenses already carried the column.
        ("housing", "paid_by", "''"),
        ("flights", "paid_by", "''"),
        ("transportation", "paid_by", "''"),
        # IANA zone per airport — see migration 021.
        ("airports", "tz", "''"),
    ]:
        try:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT {defval}"
            )
        except Exception:
            db.logger.debug("bootstrap ALTER TABLE %s ADD COLUMN %s skipped", table, col, exc_info=True)
    for table, col in [
        ("activities", "lat"),
        ("activities", "lng"),
        ("activities", "score"),
        ("activities", "score_p"),
        ("activities", "score_c"),
        ("activities", "true_score"),
        ("housing", "lat"),
        ("housing", "lng"),
        ("transportation", "lat"),
        ("transportation", "lng"),
        ("housing", "baths"),
        ("housing", "bedrooms"),
        ("housing", "deposit"),
        ("housing", "rating"),
        # cents per point on this line, NULL = use the 1.7c default (migration 016)
        ("housing", "cents_per_point"),
        ("flights", "cents_per_point"),
        ("transportation", "cents_per_point"),
        # Geocode cache for guest_codes.address — see migration 018. The
        # address stays account-only; these are what the day-of ride chain
        # needs to name a stop, and they never leave the private Hub.
        ("guest_codes", "home_lat"),
        ("guest_codes", "home_lng"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")
        except Exception:
            db.logger.debug("bootstrap ALTER TABLE %s ADD COLUMN %s skipped", table, col, exc_info=True)
    # Nullable counts and flags. Distinct from the counter loop below: these
    # have to stay NULL when unset, because 0 is a real answer here — a stay
    # with `points_total` 0 is a cash booking, one with NULL was never priced
    # in points at all, and the fare table renders those differently.
    for table, col in [
        ("housing", "beds"),
        ("housing", "guests"),
        ("housing", "hot_tub"),
        ("housing", "pool"),
        ("housing", "pool_table"),
        ("housing", "reviews"),
        ("housing", "points_nightly"),
        ("housing", "points_total"),
        ("housing", "points_transfer"),
        ("flights", "points_total"),
        ("flights", "points_transfer"),
        ("transportation", "points_total"),
        ("transportation", "points_transfer"),
        ("transportation", "seats"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER")
        except Exception:
            db.logger.debug("bootstrap ALTER TABLE %s ADD COLUMN %s skipped", table, col, exc_info=True)
    # Counters, not text. The TEXT loop above would store the default as '0',
    # and a '0' read back is truthy — so `strikes or 0` keeps the string and
    # `strikes + 1` raises.
    for table, col in [
        ("guest_gate_stats", "strikes"),
        ("guest_gate_stats", "window_fails"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
        except Exception:
            db.logger.debug("bootstrap ALTER TABLE %s ADD COLUMN %s skipped", table, col, exc_info=True)
    # Research is for choosing a flight; once his own (no passenger) is booked it
    # is noise. A trigger, so every write path clears it, not just the Hub's.
    # After the ALTER pass because it reads flights.passenger.
    for event in ("INSERT", "UPDATE OF status, passenger"):
        name = "flight_research_clear_" + event.split()[0].lower()
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {event} ON flights"
            " WHEN NEW.status = 'booked' AND COALESCE(NEW.passenger, '') = ''"
            " BEGIN DELETE FROM flight_research WHERE trip_id = NEW.trip_id; END"
        )
    # Rows that predate the split still only have `name`. Fill the parts from
    # it once so the panel opens on the person's actual name rather than two
    # blanks. Everything past the first space is the last name — wrong for a
    # middle name, right for the shape almost every guest types, and Sam
    # can edit it in the panel either way.
    conn.execute(
        "UPDATE guest_codes"
        "   SET first_name = TRIM(SUBSTR(name, 1, INSTR(name || ' ', ' ') - 1)),"
        "       last_name  = TRIM(SUBSTR(name, INSTR(name || ' ', ' ') + 1))"
        " WHERE COALESCE(first_name, '') = '' AND COALESCE(last_name, '') = ''"
    )
