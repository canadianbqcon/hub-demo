-- Migration 008_flight_passenger for trips.db
-- Generated: 2026-08-11
-- Purpose: the flights table was doing two jobs under one name. Rows in a
-- direction group are ALTERNATIVE FARES for one seat — `flightLegs` groups by
-- `direction` and `picked`/`autoPick` chooses among them to drive the arrival
-- timeline, the map pin and the "a seat, all-in" figure. So a fellow traveller's
-- leg had nowhere to live: dropping it in contests Sam's own pick, and
-- leaving it out keeps it off the trip calendar, which is where knowing who
-- lands when actually matters.
--
--   passenger  who this leg belongs to. EMPTY means Sam — the fare board and
--              every money figure read only the empty rows, so the decision
--              surface is unchanged. A named row is somebody else's ticket:
--              excluded from the fare comparison, included in the itinerary.
--
-- Free text rather than a members FK on purpose. A row can belong to two people
-- on one booking ("Aaron + Jasmine"), and the itinerary only ever prints the
-- string. Nothing joins on it.

-- +migrate up

ALTER TABLE flights ADD COLUMN passenger TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without this column and migrate data across.
-- Low-risk add (nullable column, defaults to the existing Sam-only meaning).
