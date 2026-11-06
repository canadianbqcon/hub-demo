-- +migrate up
-- Phase C-v2.2 of the batch-prep planner. A raw step's right-hand column must show
-- EVERY quantity value (left column is the name only) — e.g. "4485 g + 2 quart".
-- The gram part lives in qty_g (toggles g/oz); the non-gram addends (quarts, oz,
-- bottles …), summed per unit and joined, live here as static text.

ALTER TABLE prep_day_step ADD COLUMN qty_extra TEXT;

-- +migrate down
ALTER TABLE prep_day_step DROP COLUMN qty_extra;
