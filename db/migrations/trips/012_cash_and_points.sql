-- Migration 012_cash_and_points for trips.db
-- Generated: 2026-08-14
-- Purpose: every bookable row (housing, flights, transportation) could only ever
-- state a cash price. Award bookings have no cash price and a cash row has no
-- points price, so the single `cost` column forced one of two bad outcomes: an
-- award option got written as its taxes-only cash figure (looks absurdly cheap
-- next to a real fare), or the points cost got buried in free-text `notes` where
-- nothing can total it.
--
-- Split the two. Cash columns stay exactly as they are. Points get their own
-- nullable columns alongside, so a listing can carry cash, points, both, or
-- neither. NULL means "this listing has no price of that kind" — an Airbnb has
-- no points price, an award seat has no cash fare — and the UI renders a dash
-- rather than a zero. Zero would read as free; the dash reads as not relevant,
-- which is the actual fact.
--
-- `points_program` names the currency, because the number alone is meaningless:
-- 18,000 World of Hyatt points and 18,000 Chase UR are different amounts of
-- money, and after 2026-10-01 they are not even a 1:1 conversion.
--
--   points_nightly   housing only, per-night award rate, mirrors nightly_rate
--   points_total     total award cost for the stay/fare, mirrors total_cost/cost
--   points_program   'World of Hyatt' | 'Aeroplan' | 'IHG One Rewards' | ...
--   points_transfer  what it costs in Chase UR to produce points_total, since
--                    the transfer ratio is the number that actually leaves his
--                    account and it moves (Hyatt goes 1:1 -> 4:3 on 2026-10-01)

-- +migrate up

ALTER TABLE housing        ADD COLUMN points_nightly  INTEGER;
ALTER TABLE housing        ADD COLUMN points_total    INTEGER;
ALTER TABLE housing        ADD COLUMN points_program  TEXT DEFAULT '';
ALTER TABLE housing        ADD COLUMN points_transfer INTEGER;

ALTER TABLE flights        ADD COLUMN points_total    INTEGER;
ALTER TABLE flights        ADD COLUMN points_program  TEXT DEFAULT '';
ALTER TABLE flights        ADD COLUMN points_transfer INTEGER;

ALTER TABLE transportation ADD COLUMN points_total    INTEGER;
ALTER TABLE transportation ADD COLUMN points_program  TEXT DEFAULT '';
ALTER TABLE transportation ADD COLUMN points_transfer INTEGER;

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate each table without these columns and migrate data across.
-- Low-risk add (nullable columns, no data loss, no existing column touched).
