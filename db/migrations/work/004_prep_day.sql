-- +migrate up
-- Phase C of the batch-prep dashboard (design doc:
-- docs/archive/specs/2026-06-05-jc-batch-prep-dashboard-design.md → "Prep-day
-- planner" + "Phase C — prep-day persistence").
--
-- Persists a prep-day session: the recipes selected, and the generated, ordered,
-- quantity-aggregated step list with check state, so the checklist survives a
-- phone refresh. "Reset per shift" sets `cleared` on the active day; the active
-- day is the latest row with cleared IS NULL.
--
-- Step generation (BOM explosion + aggregation + juice/prep/batch sequencing) is
-- done in the app (batch_prep/db.py) and written here; this schema only stores
-- the result. No `location_id` on a step — the textual-map pivot (migration 003)
-- dropped structured per-recipe locations, so steps carry no location column.

CREATE TABLE prep_day (
    id      INTEGER PRIMARY KEY,
    started TEXT NOT NULL DEFAULT (datetime('now')),
    cleared TEXT                              -- NULL while active; set on reset
) STRICT;

CREATE TABLE prep_day_selection (
    prep_day_id INTEGER NOT NULL REFERENCES prep_day(id) ON DELETE CASCADE,
    recipe_id   INTEGER NOT NULL REFERENCES recipes(id),
    PRIMARY KEY (prep_day_id, recipe_id)
) STRICT;

CREATE TABLE prep_day_step (
    id          INTEGER PRIMARY KEY,
    prep_day_id INTEGER NOT NULL REFERENCES prep_day(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    phase       TEXT NOT NULL,                -- 'juice' | 'prep' | 'batch'
    label       TEXT NOT NULL,
    qty_g       REAL,                         -- combined grams; NULL when not gram-based
    checked     INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX idx_prep_day_step_day ON prep_day_step(prep_day_id);
CREATE INDEX idx_prep_day_selection_day ON prep_day_selection(prep_day_id);

-- +migrate down
DROP TABLE prep_day_step;
DROP TABLE prep_day_selection;
DROP TABLE prep_day;
