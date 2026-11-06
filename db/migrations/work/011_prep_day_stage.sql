-- +migrate up
-- Staged additions to an active prep day (design doc:
-- docs/archive/specs/2026-06-06-prep-day-staged-additions-design.md).
--
-- A prep day becomes an ordered series of stages. Stage 0 is the original plan;
-- each "add" appends a self-contained raw → build-up → assemble block as the next
-- stage, after everything already there, leaving prior steps + their check state
-- untouched. `stage` tags every step and selection row to its block. It defaults
-- to 0, so every existing row is correctly the original plan.

ALTER TABLE prep_day_step      ADD COLUMN stage INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prep_day_selection ADD COLUMN stage INTEGER NOT NULL DEFAULT 0;

-- +migrate down
ALTER TABLE prep_day_step      DROP COLUMN stage;
ALTER TABLE prep_day_selection DROP COLUMN stage;
