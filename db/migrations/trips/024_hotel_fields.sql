-- Migration 024_hotel_fields for trips.db
-- Date: 2026-09-15
-- Purpose: give a hotel the columns a hotel actually answers.
--
-- Migration 014 split the EDIT FORM into a hotel half and a rental half, but the
-- schema behind both halves stayed a rental's. So the Columbus Hyatt's room type
-- sat inside `notes`, its loyalty number and its nightly incidental hold sat
-- inside `check_in_method`, and the panel had nowhere to print any of them as a
-- fact. Next to the Arvada rental, whose equivalent facts DO have columns, the
-- Hyatt read as a thin row rather than as a stay described differently.
--
--   room_type       what was actually booked: bed count, size, view
--   loyalty         the loyalty number the booking is under
--   incidental_hold what the front desk authorises on the card, and when it drops
--   resort_fee      the per-night charge that is not in the nightly rate
--   breakfast       included or not, and what it costs when it is not
--   late_checkout   what is available and what it takes to get it
--
-- Every one is TEXT and not a number on purpose. Each carries TERMS as well as a
-- figure ("$50/night, released 5-7 days after checkout", "2pm on request, free
-- for Explorist"), and the terms are the half that decides anything. A REAL
-- column keeps the 50 and pushes the rest back into `notes`, which is the exact
-- problem this migration exists to fix.
--
-- Deliberately not backfilled by SQL, for migration 023's reason: the facts are
-- embedded in prose written by hand, a rule that split them would guess, and
-- there is one booked hotel in this database. Hand-filling it through the form is
-- cheaper and cannot be wrong.

-- +migrate up

ALTER TABLE housing ADD COLUMN room_type TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN loyalty TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN incidental_hold TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN resort_fee TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN breakfast TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN late_checkout TEXT DEFAULT '';

-- +migrate down

ALTER TABLE housing DROP COLUMN room_type;
ALTER TABLE housing DROP COLUMN loyalty;
ALTER TABLE housing DROP COLUMN incidental_hold;
ALTER TABLE housing DROP COLUMN resort_fee;
ALTER TABLE housing DROP COLUMN breakfast;
ALTER TABLE housing DROP COLUMN late_checkout;
