-- Migration 019_grocery for trips.db
-- Generated: 2026-09-02
-- Purpose: the shopping run a trip needs on arrival. Lost Lands needed distilled
-- water bought in Columbus and there was nowhere on the board to say so, so it
-- lived in someone's head until the shop was already behind them.
--
-- Two pieces, because a grocery run is a list AND a moment:
--
-- `grocery` is the list. One row per thing to buy, `got` flipping as the cart
-- fills. It is DB state rather than a per-reader localStorage tick like the
-- day-of checklist, because one person walks the store for everybody and a tick
-- only that person can see is a second trip for the water.
--
-- `trips.grocery_when` is the moment, and it is a RELATION, not a timestamp:
-- 'after' (the default, and what an empty string means) puts the run after you
-- have the room, 'before' puts it between landing and check-in for the trips
-- where the flight gets in early enough that arriving with the water beats
-- going back out for it. Storing the relation rather than a date is what keeps
-- it right when the stay is rebooked — a copied-down datetime would quietly go
-- stale against the check-in it was derived from.

-- +migrate up

CREATE TABLE IF NOT EXISTS grocery (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id    INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    item       TEXT NOT NULL,
    qty        TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    got        INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_grocery_trip ON grocery(trip_id);

ALTER TABLE trips ADD COLUMN grocery_when TEXT DEFAULT '';

-- +migrate down

DROP INDEX IF EXISTS idx_grocery_trip;
DROP TABLE IF EXISTS grocery;
-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse grocery_when: recreate `trips` without it and migrate data across.
-- Low-risk add (one nullable TEXT column, no data loss, no existing column touched).
