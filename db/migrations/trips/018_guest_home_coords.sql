-- Migration 018_guest_home_coords for trips.db
-- Generated: 2026-08-28
-- Purpose: the day-of "getting there" card can chain one rideshare from the
-- furthest traveller to the nearest and on to the terminal, so seven people on
-- one morning flight take one car instead of four. That needs each traveller's
-- home as a POINT, not as prose: Uber's deep link takes a latitude/longitude
-- pair per stop and Lyft's takes nothing else at all.
--
-- The address itself already exists — guest_codes.address, which each person
-- typed about themselves on their own account page. These two columns are its
-- geocode cache, filled by the trip geocode pass, so the page never makes a
-- network call to draw a link.
--
-- Nothing here changes who can SEE an address. guest_codes.address is
-- account-only by design (see db.GUEST_FIELDS) and these coordinates inherit
-- that: db.get_full_trip attaches a member's home only when the caller is the
-- private Hub, never the public mirror and never a Hub guest preview. A shared
-- itinerary link must not hand every guest everybody's doorstep.

-- +migrate up

ALTER TABLE guest_codes ADD COLUMN home_lat REAL;
ALTER TABLE guest_codes ADD COLUMN home_lng REAL;

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate guest_codes without these columns and migrate data across.
-- Low-risk add (two nullable REAL columns, no data loss, no existing column touched).
