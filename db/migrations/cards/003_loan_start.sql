-- Migration 003_loan_start for cards.db
-- Generated: 2026-07-27
--
-- Purpose: installment loans need an origination date. Without it, `balance` on a
-- loan row has to be hand-refreshed to stay true, which guarantees it goes stale.
-- With it, the projection amortizes forward from origination to today and derives
-- the current principal itself — the seed only ever states facts that don't move
-- (original principal, rate, term, installment).
--
-- Split from 002 rather than folded into it because 002 was already applied; a
-- down-migration to amend it would drop columns from a live table for no gain.

-- +migrate up

ALTER TABLE card ADD COLUMN start_date TEXT;  -- ISO origination date; loans only

-- +migrate down

ALTER TABLE card DROP COLUMN start_date;
