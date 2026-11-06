-- Migration 016_points_rate for trips.db
-- Generated: 2026-08-25
-- Purpose: a line bought with points has no honest single price, because the
-- points-to-dollars rate was a global 1.7c constant in trips-cost.js with one
-- hardcoded per-hotel exception beside it
-- (`RATE_EXCEPTIONS = { "Hyatt Regency Columbus": 0.0340013698630137 }`).
-- The two disagreed on screen: the cost table priced trip 59's stay at the flat
-- rate ($600.00) while the settlement priced it at the exception ($1,200.00).
-- Same row, same points, two numbers.
--
-- `cents_per_point` makes the rate a property of the row, so there is only ever
-- one of it. NULL means "no rate set on this line" and the reader falls back to
-- the 1.7c default, which is what every row without a redemption of its own
-- should do. Stored in CENTS per point (1.7, 3.4), not dollars per point
-- (0.017), because cents is the unit award redemptions are quoted in and the
-- unit Sam speaks in; the read site divides by 100.
--
-- Only housing / flights / transportation get the column — they are the only
-- tables with points columns at all. `expenses` has none and is untouched.
--
-- The seed below carries the retired exception forward verbatim, so behaviour is
-- preserved exactly on the one row that had it, and the number becomes editable.

-- +migrate up

ALTER TABLE housing        ADD COLUMN cents_per_point REAL;
ALTER TABLE flights        ADD COLUMN cents_per_point REAL;
ALTER TABLE transportation ADD COLUMN cents_per_point REAL;

UPDATE housing SET cents_per_point = 3.40013698630137
 WHERE name = 'Hyatt Regency Columbus';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate each table without this column and migrate data across,
-- and restore RATE_EXCEPTIONS in trips-cost.js.
-- Low-risk add (one nullable column per table, no data loss, no existing column touched).
