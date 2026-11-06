-- Migration 022_packing_ticks for trips.db
-- Date: 2026-09-09
-- Purpose: give each trip its own packing tick state.
--
-- The packing tab draws Sam's real lists out of checklists.db and, until now,
-- wrote a tick straight back to the /checklists row. That makes "packed" a
-- property of the LIST rather than of the trip: packing for Denver left the
-- Toiletries list permanently half-ticked on /checklists, and the next trip
-- opened onto somebody else's progress. Contents stay over there — they are one
-- set of lists and editing them in one place is the point — and the state moves
-- here, keyed by trip.
--
-- Absent row = not packed, so a new trip starts clean with nothing to seed.
-- list_id/item_id are checklists.db ids and deliberately carry no foreign key:
-- the two databases are separate files, and an item deleted over there simply
-- stops being drawn, leaving a harmless orphan row.

-- +migrate up

CREATE TABLE IF NOT EXISTS packing_ticks (
    trip_id   INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    list_id   INTEGER NOT NULL,
    item_id   INTEGER NOT NULL,
    ticked_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (trip_id, list_id, item_id)
);

-- +migrate down

DROP TABLE IF EXISTS packing_ticks;
