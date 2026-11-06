-- +migrate up
-- Juniper & Co recipe database. Headless (no dashboard module) as of 2026-05-29.
-- Onboarded via wiki/decisions/onboard-jc-database.md.
-- Three recipe kinds (cocktail / batch / prep) share one table; ingredients and
-- inter-recipe dependencies (cocktail->batch, batch->prep) are child tables.

CREATE TABLE recipes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,          -- 'cocktail' | 'batch' | 'prep'
    name        TEXT NOT NULL,
    category    TEXT,                   -- cocktail: menu section; batch: batch type; prep: prep category
    glassware   TEXT,                   -- cocktail only
    garnish     TEXT,                   -- cocktail only
    description TEXT,                   -- cocktail tasting note / riff description
    method      TEXT,                   -- prep/batch build steps + dilution formula
    allergy     TEXT,                   -- allergy flags (nut, fish, etc.)
    menu        TEXT NOT NULL,          -- 'summer-2026' | 'prior-2026-05' (provenance for the merge)
    notes       TEXT,                   -- upcharge options, misc
    wiki_slug   TEXT,                   -- cross-reference to a wiki node, if any
    created     TEXT NOT NULL DEFAULT (datetime('now')),
    updated     TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE TABLE recipe_ingredients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient  TEXT NOT NULL,
    amount      TEXT,                   -- free-text measure: "2.25 oz", "4500ml (6x750ml)", "2 dash"
    sort_order  INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE recipe_dependencies (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id            INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    depends_on_recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    note                 TEXT                -- e.g. 'batch base', 'prep input'
) STRICT;

CREATE INDEX idx_recipes_kind ON recipes(kind);
CREATE INDEX idx_recipes_menu ON recipes(menu);
CREATE INDEX idx_ingredients_recipe ON recipe_ingredients(recipe_id);
CREATE INDEX idx_deps_recipe ON recipe_dependencies(recipe_id);

-- +migrate down
DROP TABLE recipe_dependencies;
DROP TABLE recipe_ingredients;
DROP TABLE recipes;
