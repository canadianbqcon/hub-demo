-- Migration 005_decision_outcome_fields for purchases.db
-- Generated: 2026-06-22
--
-- Purpose:
--   Add a post-purchase reflection block to decisions, mirroring the jobs
--   module's "closed" post-mortem (closed_well / closed_didnt / closed_reason).
--   Once a decision is decided and the item bought, the verdict tab can capture
--   whether it was the right call:
--     outcome_rating    1-5 satisfaction (nullable until rated)
--     outcome_well      what the purchase got right
--     outcome_regret    what disappointed / what you'd change
--     would_repurchase  yes | no | maybe | '' (unanswered)
--     decided_date      when the decision was finalised
--
--   decisions is a loose (non-STRICT) baseline table, so plain ALTER ADD COLUMN
--   is correct here — no table rebuild. Existing rows backfill to '' / NULL.
--   The db.init() fresh-machine bootstrap mirrors these columns via its
--   try/except ADD COLUMN block so a brand-new DB matches.

-- +migrate up

ALTER TABLE decisions ADD COLUMN outcome_rating   INTEGER;
ALTER TABLE decisions ADD COLUMN outcome_well     TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN outcome_regret   TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN would_repurchase TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN decided_date     TEXT NOT NULL DEFAULT '';

-- +migrate down

ALTER TABLE decisions DROP COLUMN decided_date;
ALTER TABLE decisions DROP COLUMN would_repurchase;
ALTER TABLE decisions DROP COLUMN outcome_regret;
ALTER TABLE decisions DROP COLUMN outcome_well;
ALTER TABLE decisions DROP COLUMN outcome_rating;
