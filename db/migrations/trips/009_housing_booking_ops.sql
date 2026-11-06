-- Migration 009_housing_booking_ops for trips.db
-- Generated: 2026-08-11
-- Purpose: `housing` was a comparison table. Every column on it answers "is this
-- the one" — price, beds, baths, rating, amenity flags — and none of them answer
-- "we're standing outside it on Thursday, now what". Once a row flips to `booked`
-- the comparison columns go quiet and a different set of facts becomes the whole
-- point: who the host is, how the door opens, what the house forbids, what you
-- have to do before you leave, and when the money stops being refundable.
--
-- Same move migration 007 made for a rental car: the row that got picked needs
-- its own operational vocabulary, added as nullable columns the losing rows
-- simply leave blank. No second table, no status-dependent schema.
--
--   host                  free text, host and co-host on one line
--   check_in_method       how you actually get in (smart lock / lockbox / meet
--                         the host) plus what has to happen first
--   house_rules           the binding ones, in the host's own terms — the fine
--                         print that costs money to discover on arrival
--   checkout_tasks        the chores the listing makes you do before you go
--   cancellation_deadline free-text stamp, same shape as check_in
--                         ("2026-09-03 16:00") -> TripTime.parseStamp
--   deposit               security deposit at risk, NULL when the listing
--                         doesn't name one

-- +migrate up

ALTER TABLE housing ADD COLUMN host                  TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN check_in_method       TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN house_rules           TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN checkout_tasks        TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN cancellation_deadline TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN deposit               REAL;

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without these columns and migrate data across.
-- Low-risk add (nullable columns, no data loss).
