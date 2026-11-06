-- Migration 001_initial for trips.db
-- Generated: 2026-05-22
-- Source: snapshot of existing schema at Phase 1 Step 2.
-- This is a BASELINE migration. The four databases already contain these
-- tables before Phase 1; this file documents that starting state so future
-- migrations have a known baseline to diff against.
--
-- Apply with: python data/migrate.py baseline trips
-- (DO NOT run via `up` against the existing databases — the CREATE
--  statements will collide with the live tables. `baseline` records
--  this migration as applied without executing the SQL.)

-- +migrate up

-- table: activities
CREATE TABLE activities (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                location    TEXT DEFAULT '',
                description TEXT DEFAULT '',
                cost        REAL,
                url         TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                status      TEXT DEFAULT 'considering'
            , tags TEXT DEFAULT '', scheduled_date TEXT DEFAULT '', scheduled_time TEXT DEFAULT '', lat REAL, lng REAL, score REAL, score_p REAL, score_c REAL, operating_days TEXT DEFAULT '', operating_hours TEXT DEFAULT '', scheduled_time_end TEXT DEFAULT '', decision_reason TEXT DEFAULT '', true_score REAL, cal_event_id TEXT DEFAULT '', group_identity TEXT DEFAULT '', log_notes TEXT DEFAULT '');

-- table: activity_opinions
CREATE TABLE activity_opinions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                rating      INTEGER,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(activity_id, member_id)
            );

-- table: expenses
CREATE TABLE expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                category    TEXT DEFAULT 'misc',
                description TEXT DEFAULT '',
                amount      REAL DEFAULT 0,
                currency    TEXT DEFAULT 'USD',
                paid_by     TEXT DEFAULT '',
                status      TEXT DEFAULT 'estimated'
            );

-- table: flights
CREATE TABLE flights (
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
            , terminal_from TEXT DEFAULT '', terminal_to TEXT DEFAULT '', location TEXT DEFAULT '');

-- table: housing
CREATE TABLE housing (
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
            , lat REAL, lng REAL);

-- table: members
CREATE TABLE members (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                name    TEXT NOT NULL,
                email   TEXT DEFAULT '',
                notes   TEXT DEFAULT ''
            , contact_slug TEXT DEFAULT '');

-- table: transportation
CREATE TABLE transportation (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                type        TEXT DEFAULT 'other',
                description TEXT DEFAULT '',
                departure   TEXT DEFAULT '',
                arrival     TEXT DEFAULT '',
                cost        REAL,
                notes       TEXT DEFAULT '',
                status      TEXT DEFAULT 'considering'
            , location TEXT DEFAULT '', url TEXT DEFAULT '', scheduled_date TEXT DEFAULT '', scheduled_time TEXT DEFAULT '');

-- table: trips
CREATE TABLE trips (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                destination TEXT DEFAULT '',
                start_date  TEXT DEFAULT '',
                end_date    TEXT DEFAULT '',
                cal_event_id TEXT UNIQUE,
                notes       TEXT DEFAULT ''
            , trip_interests TEXT DEFAULT '');

-- +migrate down
-- No-op. Rolling back the baseline is not a meaningful operation —
-- it would mean dropping every table and losing all data. If you
-- truly need a fresh database, delete the .db file and re-baseline.
