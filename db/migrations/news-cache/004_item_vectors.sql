-- +migrate up
-- One title embedding per item, for cross-outlet grouping when token overlap
-- misses a re-worded headline. `model` is stored so a model swap leaves old
-- rows ignored (embed.load skips them) instead of mixed into new comparisons.
-- vec is 768 little-endian float32, L2-normalized.

CREATE TABLE IF NOT EXISTS item_vectors (
    item_id INTEGER PRIMARY KEY,
    model   TEXT NOT NULL,
    vec     BLOB NOT NULL
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS item_vectors;
