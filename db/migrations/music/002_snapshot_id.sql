-- Migration 002_snapshot_id for music.db
-- Generated: 2026-09-28
--
-- Spotify's version tag per playlist, as of the last pull that read it. The pull
-- skips any playlist whose tag has not changed, so a night costs a handful of
-- requests instead of reading all 200 lists (the full read tripped a 21-hour
-- rate-limit lockout on 2026-09-28). NULL = never read by a pull, so read it.

-- +migrate up

ALTER TABLE playlists ADD COLUMN snapshot_id TEXT;

-- +migrate down

ALTER TABLE playlists DROP COLUMN snapshot_id;
