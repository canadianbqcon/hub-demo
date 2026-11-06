-- +migrate up
-- Stage B of the prep-day redesign (design doc:
-- docs/archive/specs/2026-06-07-prep-day-redesign-design.md).
--
-- The checkable unit moves OFF the step header and ONTO the recipe sub-items —
-- the build-up/assemble composition rows. Each component carries its own check so
-- you tick the actual ingredient you've added, not a whole batch at once. Raw is a
-- plain gather list (Stage A3), so its steps stay uncheckable. Defaults to 0, so
-- every existing component starts unchecked.

ALTER TABLE prep_day_step_component ADD COLUMN checked INTEGER NOT NULL DEFAULT 0;

-- +migrate down
ALTER TABLE prep_day_step_component DROP COLUMN checked;
