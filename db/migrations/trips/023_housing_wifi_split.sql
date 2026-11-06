-- Migration 023_housing_wifi_split for trips.db
-- Date: 2026-09-10
-- Purpose: give the network name and the password their own columns.
--
-- Migration 010 gave wifi a column of its own so it would not be buried in
-- `notes`, and one free-text column was right for as long as the panel only had
-- to PRINT it. It stopped being right the moment the row had to DO something:
-- copying the password to the clipboard and building a join-this-network QR both
-- need to know which half is which, and "Escape The Ordinary — arvadabnb.
-- Backyard extender: ..." cannot be split by rule. A parser guessing at a dash
-- would hand somebody the wrong string at a door, which is worse than printing
-- the sentence unchanged.
--
--   wifi_ssid  the network name, exactly as it appears in the phone's wifi list
--   wifi_pass  the password, on its own so one tap can copy it
--   wifi       demoted to the REMAINDER — extenders, the 5G/2.4G split, "ask the
--              host", anything that is neither of the two above. Existing rows
--              keep whatever sentence they already hold, so nothing is lost and
--              nothing is guessed: the panel prints it under the two new fields
--              until somebody fills those in.
--
-- Deliberately not backfilled by SQL. A dash is a separator in one row and part
-- of a network name in the next, and there are ten housing rows in this database
-- — hand-filling the one stay that has wifi is cheaper and cannot be wrong.

-- +migrate up

ALTER TABLE housing ADD COLUMN wifi_ssid TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN wifi_pass TEXT DEFAULT '';

-- +migrate down

ALTER TABLE housing DROP COLUMN wifi_ssid;
ALTER TABLE housing DROP COLUMN wifi_pass;
