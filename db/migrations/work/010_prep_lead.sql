-- +migrate up
-- Per-prep brew/lead time for the prep-day build-up ordering. "Things that need
-- time to brew come first, longest first" — but dependency depth stays primary, so
-- the sort key is (-depth, -lead_minutes, name): an input prep is still made before
-- the prep it feeds; wait time only breaks ties within a depth level.
--
--   recipes.lead_minutes  passive wait until usable, in minutes (NULL/0 = no wait);
--                         the sort key. Driven by passive unattended waits — infuse,
--                         steep, rest, chill, freeze, dehydrate, sous-vide — not
--                         active simmering (which counts only when there's no passive wait).
--   recipes.lead_label    the exact human display text ("infuse overnight",
--                         "sous vide 24 hr", "steep 10 min"); NULL = show nothing.
--   prep_day_step.lead_label  snapshot stamped on each build-up step at build time so
--                         the persisted checklist survives a phone refresh.
--
-- Seed applied separately (seed_prep_lead.py) per the storage_note / ingredient_tier
-- precedent: migrations carry schema, seeds carry data. Card-stated times where the
-- card gives one; web-researched (with a note on the row) where it doesn't.

ALTER TABLE recipes ADD COLUMN lead_minutes INTEGER;
ALTER TABLE recipes ADD COLUMN lead_label TEXT;
ALTER TABLE prep_day_step ADD COLUMN lead_label TEXT;

-- +migrate down
ALTER TABLE prep_day_step DROP COLUMN lead_label;
ALTER TABLE recipes DROP COLUMN lead_label;
ALTER TABLE recipes DROP COLUMN lead_minutes;
