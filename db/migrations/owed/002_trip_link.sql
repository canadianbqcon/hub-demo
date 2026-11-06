-- Migration 002_trip_link for owed.db
-- Generated: 2026-08-28
-- Purpose: a debt that came out of a trip has its amount computed on the trips
-- board — a share of a stay, a seat, a van — and the owed tab held a hand-typed
-- copy of that number. Sam, 2026-08-28: "the cost, if it changes in trips,
-- should automatically update the owed tab correctly." A copy cannot do that.
--
-- Two columns, no second table:
--
--   src        a stable pointer at the trip line and the person who owes their
--              share of it: "trip:<trip_id>/<table>/<row_id>/member:<member_id>".
--              NULL on every hand-entered row, which is what keeps them
--              hand-entered — the sync only ever touches rows that have one.
--   src_amount the value the sync last derived for that pointer.
--
-- src_amount is what makes an override possible without a flag anyone has to
-- remember to set. On each sync the derived value is recomputed; if `amount`
-- still equals `src_amount` nobody has touched it, so both move to the new
-- figure. If they differ, Sam typed his own number over it (Aria's El
-- Salvador ticket is $450, not the $520.00 the fare and the points add up to),
-- and the sync leaves `amount` alone and only refreshes `src_amount`, so the
-- override survives every later trip edit instead of being silently clobbered.
--
-- Settlement state stays here and only here. trips.db has nowhere to record
-- that someone paid, which is the whole reason these rows exist rather than the
-- owed tab reading the trips ledger live.

-- +migrate up

ALTER TABLE owed ADD COLUMN src        TEXT;
ALTER TABLE owed ADD COLUMN src_amount REAL;

CREATE UNIQUE INDEX owed_src ON owed (src) WHERE src IS NOT NULL;

-- +migrate down

DROP INDEX IF EXISTS owed_src;
-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate owed without these two columns and migrate data across.
-- Low-risk add (two nullable columns, no data loss, no existing column touched).
