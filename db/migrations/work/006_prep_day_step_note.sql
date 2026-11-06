-- +migrate up
-- Phase C-v2.1 of the batch-prep planner. A build-up step now reproduces the
-- sub-recipe's card verbatim (ingredients in original units + the method), so it
-- needs somewhere to carry that method line ("let sit 10 mins, strain and QT").
-- One nullable note column on the step; raw/assemble steps leave it NULL.

ALTER TABLE prep_day_step ADD COLUMN note TEXT;

-- +migrate down
ALTER TABLE prep_day_step DROP COLUMN note;
