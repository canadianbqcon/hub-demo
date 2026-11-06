-- Migration 007_transport_rental_fields for trips.db
-- Generated: 2026-08-11
-- Purpose: a rental car is a decision with a clock on it, and the transportation
-- table had nowhere to put that clock. `departure`/`arrival` are free-text PLACES
-- ("Union Station" -> "Boulder") for a bus or a train, so a rental was writing its
-- pickup and drop-off into prose where nothing could compare them against the
-- flights they exist to bracket.
--
-- Three columns, all nullable, all ignored by the bus/train rows that don't have them:
--
--   pickup_time  free-text stamp, same shape as flights.departure_time
--                ("2026-09-10 09:30" | "Sep 10, 9:30 AM") -> TripTime.parseStamp
--   dropoff_time same
--   seats        how many people the vehicle actually holds, so a party of 7 in a
--                5-seat SUV reads as a flag and not as a fine option
--
-- The three sub-boards on the transportation section (rental / turo / everything
-- else) split on `type`, which already exists — 'car_rental', 'turo', anything
-- else falls through to the flexible group. No new table, no type column rename.

-- +migrate up

ALTER TABLE transportation ADD COLUMN pickup_time  TEXT DEFAULT '';
ALTER TABLE transportation ADD COLUMN dropoff_time TEXT DEFAULT '';
ALTER TABLE transportation ADD COLUMN seats        INTEGER;

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without these columns and migrate data across.
-- Low-risk add (nullable columns, no data loss).
