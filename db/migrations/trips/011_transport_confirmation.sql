-- Migration 011_transport_confirmation for trips.db
-- Generated: 2026-08-13
-- Purpose: the flights and housing boards each hand over to a reference panel once
-- a row is booked, and both had somewhere to put the one string you actually need
-- at the counter — `flights.confirmation`, `housing.confirmation_code`. The
-- transportation table had neither. A confirmed rental car (trip 1, Enterprise at
-- AUS) carries a pickup location, a time and a price, and no way to say which
-- booking it is, so the number was going into `notes` prose where the panel cannot
-- read it and no form field asks for it.
--
--   confirmation  the rental's own booking reference. Free text and not a code
--                 format, because every operator words it differently (Enterprise
--                 prints a confirmation number, Turo shows a trip ID) and nothing
--                 joins on it.
--
-- One column, not a set. Everything else a booked car needs is already on the row:
-- migration 007 gave it the pickup/drop-off clock and the seat count, `location`
-- holds the counter address, `url` the booking page. This is the only fact with
-- nowhere to live.
--
-- ponytail: no `driver` or `insurance` column. Neither has a second reader today
--   and both sit fine in notes; add them when something needs to render one on
--   its own rather than as a line in the notes list.

-- +migrate up

ALTER TABLE transportation ADD COLUMN confirmation TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without this column and migrate data across.
-- Low-risk add (nullable column, no data loss).
