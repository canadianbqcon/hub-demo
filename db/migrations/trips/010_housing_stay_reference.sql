-- Migration 010_housing_stay_reference for trips.db
-- Generated: 2026-08-13
-- Purpose: migration 009 gave a booked stay the facts you need on the doorstep —
-- who the host is, how the door opens, what the house forbids, what to do before
-- you leave. It stopped short of the facts you need for the four days AFTER the
-- doorstep, which is where most of the questions actually land: is there a washer,
-- do I need to bring a towel, is there a grill, what is the wifi.
--
-- Two columns, because those questions split exactly two ways.
--
--   amenities  the listing's full "what this place offers" list, one item per
--              BLANK-LINE-separated block, IN THE ORDER THE LISTING GIVES IT.
--              The separator is a blank line and not a newline because an item
--              carries its own sub-detail on the line under it ("Essentials\n
--              Towels, bed sheets, soap, and toilet paper"), so splitting on a
--              single \n would shatter nine of Denver's sixty-three items into
--              orphan fragments. That order is Airbnb's
--              own section order (bathroom, then bedroom and laundry, then
--              entertainment, family, heating, safety, internet, kitchen,
--              outdoor, parking), so storing it verbatim keeps the grouping for
--              free and no classifier has to guess at one. The front end shows
--              an item's sub-detail on hover rather than in the chip.
--              Blank means the list was never read, which is not the same as a
--              spartan listing, so the surface says "not read yet" rather than
--              drawing an empty amenity block.
--   wifi       network and password. Deliberately its own column and not part of
--              check_in_method: getting in happens once and this gets asked all
--              week, by seven people, usually from the couch. It also arrives on
--              a different clock — Airbnb releases it 48 hours before check-in —
--              so it is normal for this to sit blank next to a filled-in
--              check_in_method, and the stay panel says so in those words.
--
-- ponytail: the door code stays inside check_in_method as prose rather than
--   getting a column of its own. It is one short string that only ever reads
--   alongside "how do you get in", and every listing words it differently
--   (smart lock, lockbox, keypad, meet the host). Give it a column when a second
--   consumer needs to read it on its own.

-- +migrate up

ALTER TABLE housing ADD COLUMN amenities TEXT DEFAULT '';
ALTER TABLE housing ADD COLUMN wifi      TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without these columns and migrate data across.
-- Low-risk add (nullable columns, no data loss).
