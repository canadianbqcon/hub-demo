-- +migrate up
-- Retire the vestigial step-level check. The checkable unit moved OFF the step
-- header and onto the composition rows in Stage B (migration 012 added
-- prep_day_step_component.checked); a step header's done/total is now derived from
-- its components. Since then prep_day_step.checked has been written by nothing and
-- read by nothing (the app dropped its toggle_step path and stopped selecting the
-- column), so drop it. Component progress lives in prep_day_step_component.checked —
-- a DIFFERENT table and column — and is untouched, so no live prep-day check is lost.

ALTER TABLE prep_day_step DROP COLUMN checked;

-- +migrate down
ALTER TABLE prep_day_step ADD COLUMN checked INTEGER NOT NULL DEFAULT 0;
