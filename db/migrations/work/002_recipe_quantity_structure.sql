-- +migrate up
-- Phase A of the batch-prep dashboard (design doc:
-- docs/archive/specs/2026-06-05-jc-batch-prep-dashboard-design.md).
-- Structures the free-text `recipe_ingredients.amount` into machine-scalable
-- fields so a viewer can rescale a batch proportionally, and records each
-- prep/batch's total yield so a sub-recipe can be scaled to a required amount.
-- These columns are added empty (nullable); they are populated only after the
-- Phase A quantity review sheet is confirmed by Sam (nothing guessed
-- silently). `amount` is kept verbatim for display/provenance.
--
-- Unit basis: grams is canonical; 1 oz = 29.5735 g (fluid-oz-of-water — the
-- convention the photographed recipe cards use; see the design doc units model).
-- Storage links (recipes.location_id, FK -> storage_location) are deferred to
-- the Phase A2 migration that creates the storage_location table.

ALTER TABLE recipe_ingredients ADD COLUMN qty REAL;
ALTER TABLE recipe_ingredients ADD COLUMN unit TEXT;
ALTER TABLE recipe_ingredients ADD COLUMN scalable INTEGER NOT NULL DEFAULT 1;
ALTER TABLE recipe_ingredients ADD COLUMN produces_recipe_id INTEGER REFERENCES recipes(id);

ALTER TABLE recipes ADD COLUMN yield_qty REAL;
ALTER TABLE recipes ADD COLUMN yield_unit TEXT;

CREATE INDEX idx_ingredients_produces ON recipe_ingredients(produces_recipe_id);

-- +migrate down
DROP INDEX idx_ingredients_produces;
ALTER TABLE recipes DROP COLUMN yield_unit;
ALTER TABLE recipes DROP COLUMN yield_qty;
ALTER TABLE recipe_ingredients DROP COLUMN produces_recipe_id;
ALTER TABLE recipe_ingredients DROP COLUMN scalable;
ALTER TABLE recipe_ingredients DROP COLUMN unit;
ALTER TABLE recipe_ingredients DROP COLUMN qty;
