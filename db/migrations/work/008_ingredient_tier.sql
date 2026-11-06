-- +migrate up
-- Reasoned raw-stage tier classification, replacing the keyword classifier in
-- batch_prep/db.py (_perish_rank's _ALC/_FRESH/_PANTRY_FORM/_ALC_WORD substring
-- sets). One row per distinct raw ingredient name (lowercased, matching the
-- lookup key), with its prep-order tier judged per-ingredient rather than guessed
-- from substrings — so a new ingredient is classified deliberately, not silently
-- defaulted by whether it happens to contain "milk" or "gin".
--
--   tier 0 = Fresh   (juices, fresh produce, herbs)
--   tier 1 = Pantry  (dry / canned / shelf-stable non-alcohol — teas, syrups,
--                     spices, sugars, salt, sauces, canned/condensed/evaporated
--                     + coconut milk; the catch-all)
--   tier 2 = Alcohol (every spirit, liqueur, wine, beer, bitters, N/A spirit)
--   tier 3 = Refrigerated (cold-stored, added last — dairy + eggs + fresh-pressed
--                     sugarcane juice; Sam 2026-06-06. Was "Dairy" at create
--                     time; broadened by the seed re-judge same day.)
--
-- Seed is applied separately (seed_ingredient_tiers.py) per the storage_note
-- precedent: migrations carry schema, seeds carry data. An ingredient absent from
-- this table degrades to Pantry AND is surfaced by db.missing_tiers() for review,
-- instead of silently mis-bucketing.

CREATE TABLE ingredient_tier (
    name TEXT PRIMARY KEY,                              -- lowercased ingredient name (the lookup key)
    tier INTEGER NOT NULL CHECK (tier BETWEEN 0 AND 3), -- 0 fresh · 1 pantry · 2 alcohol · 3 refrigerated
    note TEXT                                            -- optional rationale / disambiguation
) STRICT;

-- +migrate down
DROP TABLE ingredient_tier;
