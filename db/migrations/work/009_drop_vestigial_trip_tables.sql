-- +migrate up
-- Drop 8 vestigial trip-planner tables that rode along when work.db was seeded
-- from a trips.db copy. They were never created by any work/jc migration, held
-- 0 rows, and were referenced by nothing in the batch-prep schema. This migration
-- exists because work.db (formerly jc.db) was renamed/repurposed into the "work"
-- domain on 2026-06-06 (see wiki/decisions/onboard-work-module.md); the trip
-- cruft has no place in a work database. Real trip data lives in data/trips.db.
-- Drop children before parents to satisfy foreign keys.

DROP TABLE IF EXISTS activity_opinions;
DROP TABLE IF EXISTS activities;
DROP TABLE IF EXISTS members;
DROP TABLE IF EXISTS housing;
DROP TABLE IF EXISTS flights;
DROP TABLE IF EXISTS transportation;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS trips;

-- +migrate down
-- One-way. These tables were empty stray cruft, never part of the work schema,
-- and carried no data worth recreating. No down script by design; restore from
-- the pre-migration .bak if the drop ever needs reverting.
