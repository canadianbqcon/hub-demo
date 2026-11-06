-- +migrate up
-- Phase C-v2 of the batch-prep dashboard. The prep-day planner is reshaped from
-- flat juice/prep/batch steps into a ground-up read: raw -> build-up -> assemble.
-- Every made sub-recipe (build-up) and every assembled batch (assemble) now shows
-- its FULL composition — the ingredients it pulls together at the required scale —
-- not a bare "make X". Those composition lines live here, one child row per
-- component, so each gram component toggles g/oz on its own and combined-unit
-- totals (R1: never convert quart->grams) survive a phone refresh.
--
-- Step generation (BOM explosion, raw pooling, per-name unit combination,
-- dependency ordering) is done in the app (batch_prep/db.py) and the resulting
-- component list is written here; this schema only stores the result. A raw step
-- has no components (it IS a smallest part); build-up and assemble steps carry the
-- list. Components cascade-delete with their parent step (which cascades with the
-- prep_day), so clearing a day leaves no orphans.

CREATE TABLE prep_day_step_component (
    id      INTEGER PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES prep_day_step(id) ON DELETE CASCADE,
    seq     INTEGER NOT NULL,            -- render order within the step
    name    TEXT NOT NULL,               -- ingredient or made sub-recipe name
    qty_g   REAL,                        -- grams when gram-based (drives g/oz); else NULL
    unit    TEXT,                        -- 'g' | 'quart' | 'gal' | ... ; NULL for to-taste
    label   TEXT                         -- count amount ("1") or "to taste"; NULL for gram rows
) STRICT;

CREATE INDEX idx_prep_day_step_component_step ON prep_day_step_component(step_id);

-- +migrate down
DROP TABLE prep_day_step_component;
