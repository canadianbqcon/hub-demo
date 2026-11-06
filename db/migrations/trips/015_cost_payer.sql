-- Migration 015_cost_payer for trips.db
-- Generated: 2026-08-25
-- Purpose: every money table knew what a line COST and, since the split_with
-- columns, who it divided between. Neither answered the question a group trip
-- actually ends on: who put the money down, and therefore who owes them back.
-- Jasmine fronted the minivan, someone fronted the Airbnb, Sam fronted a
-- second traveller's award ticket — all of it lived in prose inside
-- `description` and `notes`, where no total could read it.
--
-- `paid_by` holds ONE members.id, as text, matching how split_with stores ids.
-- Empty means nobody has claimed the line yet: it still counts toward the trip
-- total, it just cannot enter a settlement, and the cost tab says so rather
-- than guessing an owner.
--
-- expenses already had a `paid_by` column from the original schema, but as free
-- text (a typed name). Same name, same meaning, now the same format as the other
-- three — the two rows carrying prose are rewritten to ids by the same pass that
-- applies this file, and anything unmatched is left blank rather than invented.

-- +migrate up

ALTER TABLE housing        ADD COLUMN paid_by TEXT DEFAULT '';
ALTER TABLE flights        ADD COLUMN paid_by TEXT DEFAULT '';
ALTER TABLE transportation ADD COLUMN paid_by TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate each table without this column and migrate data across.
-- Low-risk add (one nullable column per table, no data loss, no existing column touched).
