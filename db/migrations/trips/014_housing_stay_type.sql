-- Migration 014_housing_stay_type for trips.db
-- Generated: 2026-08-25
-- Purpose: the housing edit form carried all 33 columns on every row, because a
-- stay had no way to say what kind of stay it was. Half those columns are
-- meaningless for the other half of the rows: a hotel has no host, no house
-- rules, no checkout chores, no Airbnb amenity list and no security deposit,
-- while a rental has no loyalty-award price (migration 012's own note says an
-- Airbnb never will). Showing both sets to both is what made the form a wall.
--
-- `stay_type` is what the form reads to decide which half to draw:
--
--   'hotel'   hotel, resort, hostel, guesthouse, anything with a front desk
--   'rental'  Airbnb / Vrbo / whole-home, anything with a host
--
-- '' (the default) draws the hotel form, which is the common case here — 8 of
-- the 10 stays on record. No column is dropped and nothing is cleared on a
-- switch: a field the current type hides keeps whatever it already holds, so
-- flipping the type back brings its values with it.

-- +migrate up

ALTER TABLE housing ADD COLUMN stay_type TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate housing without this column and migrate data across.
-- Low-risk add (one nullable column, no data loss, no existing column touched).
