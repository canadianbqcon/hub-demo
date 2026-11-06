-- +migrate up
-- Let a grouped storage_item stand for the individual products the fill
-- checklist counts.
--
-- The two lists describe the same shelves at different altitudes. The storage
-- tree says what physically sits there, in the bar's own shorthand — Fridge 4 ·
-- Bottom is one row reading "Canisters". The lowboy_fill checklist has to be
-- per-product, because a row that says "Canisters" cannot say WHICH canister is
-- empty. So the tree groups and the checklist splits, on purpose.
--
-- Before this table that made them look diverged: two surfaces naming the same
-- shelf differently, with nothing recording that "Canisters" IS the three foams.
-- The fix Sam asked for (2026-08-02) is to keep both wordings and link them,
-- not to flatten one into the other — the grouped label is the right altitude
-- for a map you read while walking, and the split list is the right altitude for
-- a count you tick.
--
-- product is checklist_template_item.text for template lowboy_fill, matched by
-- name rather than by id: the checklist seeder deletes and re-inserts its items
-- wholesale on every run, so item ids are not stable and a FK would break on the
-- next re-seed. Names are the stable key on that side. seed_checklists.py
-- validates both ends after every seed, so a rename on either side surfaces as a
-- warning instead of a silent dangling link.

CREATE TABLE storage_item_cover (
    item_id INTEGER NOT NULL REFERENCES storage_item(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    PRIMARY KEY (item_id, product)
) STRICT;

-- +migrate down

DROP TABLE storage_item_cover;
