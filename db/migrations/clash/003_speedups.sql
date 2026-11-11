-- +migrate up
-- Active speed-ups on one running upgrade (potion, snack, helper hour). extra = rate - 1, so different
-- boosts add (Potion 10x + Bite 2x = 11x); a second of the same kind queues after the first (extends it).
-- A finish time is recomputed from the work left over these windows.
CREATE TABLE IF NOT EXISTS speedup (
    upgrade_id INTEGER NOT NULL REFERENCES upgrade(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    extra      INTEGER NOT NULL CHECK (extra > 0),
    starts_at  TEXT NOT NULL,
    until      TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS speedup_upgrade ON speedup(upgrade_id);

-- +migrate down
DROP TABLE IF EXISTS speedup;
