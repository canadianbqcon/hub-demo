-- Migration 006_housing_amenities for trips.db
-- Generated: 2026-08-11
-- Purpose: let the housing board say, per row, whether the three amenities the
-- Denver crew actually asked about are there — a hot tub, a pool table, a pool.
-- Until now the only record of them was prose inside `notes` (or a listing title
-- that says "Game Room" while the listing's own amenity list has no table on it),
-- which no badge can read.
--
-- Three columns rather than one amenity blob, because the board has to tell
-- "checked, and it isn't there" apart from "nobody checked". A red "no hot tub"
-- chip on an unverified row is a false statement, not a missing one.
--
--   NULL = not checked yet
--   0    = the listing's own full amenity list does not have it
--   1    = present
--
-- Read from the listing's "Show all N amenities" modal, not the ten shown inline
-- and not the title, since the modal list is the same data Airbnb's own filters use.

-- +migrate up

ALTER TABLE housing ADD COLUMN hot_tub    INTEGER;
ALTER TABLE housing ADD COLUMN pool_table INTEGER;
ALTER TABLE housing ADD COLUMN pool       INTEGER;

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without these columns and migrate data across.
-- Low-risk add (nullable columns, no defaults, no data loss).
