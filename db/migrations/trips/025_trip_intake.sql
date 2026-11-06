-- Migration 025_trip_intake for trips.db
-- Date: 2026-10-12
-- Purpose: hold a guest's whole-trip form submission until Sam approves it.
--
-- A guest on the public mirror can fill in a trip (basics, crew, housing,
-- flights, transport, activities, expenses) but the mirror stays read-only to
-- trip content, so a submission waits here as a pending row. Nothing is applied
-- until Sam clicks approve in the Hub access panel.
--
--   guest_key       member_key of the submitter
--   payload         the cleaned form as sent (JSON)
--   diff            payload vs the LIVE trip at submit time (JSON); what Sam
--                   approves. Rows already in trips.db are keyed `db:<id>`, rows
--                   the guest added `new:<uuid>`, so no row-mapping table exists
--   status          pending | approved | rejected | superseded
--   research_status '' | queued | running | done | failed (added activities)
--   apply_log       JSON: fields applied, conflicts skipped, errors
--
-- The rate limit counts rows here rather than an in-memory bucket, because the
-- mirror runs Restart=always and a memory counter resets on every crash.

-- +migrate up

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

-- +migrate down

DROP INDEX IF EXISTS trip_intake_guest;
DROP TABLE IF EXISTS trip_intake;
