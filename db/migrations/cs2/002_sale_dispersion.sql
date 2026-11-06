-- +migrate up
-- The item page has to defend a mark, and a median alone cannot be argued with.
-- Skinport's sales history already returns min and max inside each window; 001
-- threw them away and kept only the median, so the "here is the working" block
-- had nothing to show about spread. Store them.
--
-- Nullable on purpose: listing rows have no window to take a min/max over, and
-- snapshots written before this migration keep their NULLs rather than being
-- backfilled with a fabricated value.

ALTER TABLE item_price ADD COLUMN low_cents INTEGER;
ALTER TABLE item_price ADD COLUMN high_cents INTEGER;

-- +migrate down
ALTER TABLE item_price DROP COLUMN high_cents;
ALTER TABLE item_price DROP COLUMN low_cents;
