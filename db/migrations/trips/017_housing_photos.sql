-- Migration 017_housing_photos for trips.db
-- Generated: 2026-08-26
-- Purpose: the housing tab describes a stay entirely in words. Every fact about
-- the Denver house — 4BR, 7 beds, hot tub, pool table, Arvada — is on the board,
-- and none of it says what the place looks like, which is the first thing anyone
-- opening the tab wants and the only thing they currently have to leave for
-- Airbnb to get.
--
-- One TEXT column, one photo per line, `url` or `url<TAB>caption`. Same shape as
-- `amenities`, `house_rules` and `checkout_tasks` already on this table, which
-- the board splits on newlines — so it needs no new parser and no new table.
--
-- The URLs are Airbnb's own CDN (a0.muscache.com), stored at ?im_w=1440 and
-- hotlinked, not copied into the vault. That is deliberate: a listing's photos
-- are the host's, they are already public, and a local copy of 34 JPEGs per stay
-- is a mirror to maintain for a page that is only ever read online anyway. The
-- ceiling: if a host de-lists, the URLs 404 and the carousel goes empty. Re-run
-- .claude/skills/stays/tools/photos.py to refill, or download them if a stay
-- ever needs to survive the listing.

-- +migrate up

ALTER TABLE housing ADD COLUMN photos TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate housing without this column and migrate data across.
-- Low-risk add (one nullable text column, no data loss, no existing column touched).
