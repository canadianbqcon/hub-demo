-- Migration 004_direction for owed.db
-- Generated: 2026-09-29
-- Purpose: the tab held only money coming in. Sam, 2026-09-29, on 20 open
-- Venmo requests other people sent him: "add to owed tab as a negative and list
-- them ... each item is a separate entry it just has a negative or positive
-- value, like a transaction in my ynab".
--
-- One column, no second table:
--
--   dir   +1 = they owe him (every row before this migration), -1 = he owes
--         them. `amount` stays a non-negative magnitude so the existing CHECK
--         and every sum that already exists keep their meaning; the signed value
--         is dir * amount, and a person's card total is the net of both.
--
-- Everything that chases money (ask links, payment matching, auto-apply, group
-- fronts, "paid back") reads dir = 1 only, in owed.py.

-- +migrate up
ALTER TABLE owed ADD COLUMN dir INTEGER NOT NULL DEFAULT 1 CHECK (dir IN (1, -1));

-- +migrate down
ALTER TABLE owed DROP COLUMN dir;
