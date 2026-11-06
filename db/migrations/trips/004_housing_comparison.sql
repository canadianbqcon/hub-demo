-- Migration 004_housing_comparison for trips.db
-- Generated: 2026-08-10
-- Purpose: give housing the structured dimensions its comparison actually turns
-- on. Six Denver Airbnbs carried "6 guests max", "3BR / 4 real beds / 2.0 baths",
-- "free parking on premises", "4.97 stars, 58 reviews" as prose inside `notes`,
-- so the only thing the table could rank on was price. Every derived badge on the
-- housing panel ("won't fit at 7", "most beds", "free parking") needs these as
-- columns — parsing them back out of prose is the thing this replaces.
--
-- guests   = max occupancy the listing allows (the hard gate)
-- bedrooms/beds/baths = REAL because half-baths and 3.5 are real values
-- parking  = short phrase, '' when unknown, 'none' when known-absent
-- area     = neighbourhood, for the walkability/location read
-- rating/reviews = the trust signal, shown together or not at all

-- +migrate up

ALTER TABLE housing ADD COLUMN guests    INTEGER;
ALTER TABLE housing ADD COLUMN bedrooms  REAL;
ALTER TABLE housing ADD COLUMN beds      INTEGER;
ALTER TABLE housing ADD COLUMN baths     REAL;
ALTER TABLE housing ADD COLUMN parking   TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN area      TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN rating    REAL;
ALTER TABLE housing ADD COLUMN reviews   INTEGER;

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without these columns and migrate data across.
-- Low-risk add (nullable columns with defaults, no data loss).
