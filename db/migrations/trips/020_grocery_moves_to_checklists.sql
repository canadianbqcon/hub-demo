-- Migration 020_grocery_moves_to_checklists for trips.db
-- Date: 2026-09-02
--
-- Retires both halves of migration 019, eight days after it shipped. Neither piece
-- was wrong about what a trip needs; both were wrong about where it lives.
--
-- The LIST moves to checklists.db. Every checklist on the Hub is stored in one place
-- and shown wherever it is useful — the arrangement /recipes and /checklists already
-- had for the grocery list — so a `grocery` table in trips.db was a second copy of a
-- thing that has an owner. The trip's list is now the checklists row whose `source` is
-- 'trips:<id>:grocery'; see checklists migration 003. Run
-- db/seed_trip_grocery_move.py BEFORE this migration — it carries the rows across, with
-- their qty, note and `got` state, and this drop is what makes that move one-way.
--
-- The MOMENT is derived, not stored. `grocery_when` held which side of check-in the
-- run sat on, picked by hand in the tab head. The board already knows: the outbound
-- leg's arrival plus the bag wait gives the curb time, the booked stay gives check-in,
-- and a usable gap between them IS the answer. A pick was asking Sam a question the
-- data had already answered, and one that went stale the moment either end moved.
-- 019's own rule still holds and is the reason the column goes rather than the logic:
-- the run's timing is a RELATION to check-in, never a copied-down datetime.

-- +migrate up

DROP INDEX IF EXISTS idx_grocery_trip;
DROP TABLE IF EXISTS grocery;

ALTER TABLE trips DROP COLUMN grocery_when;

-- +migrate down

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

-- The tables come back empty. The rows themselves live in checklists.db now and this
-- rollback does not reach across to fetch them — reversing the data move means running
-- the copy the other way by hand, against the checklists rows whose source is
-- 'trips:<id>:grocery'.
