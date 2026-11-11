-- +migrate up
-- Planned upgrades waiting for a builder, the lab or the pet house (mark 2026-11-10 #5).
-- position orders the queue per village; each facility's items run in that order on the lane that frees first.
CREATE TABLE queue_item (
    id          INTEGER PRIMARY KEY,
    tag         TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    data_id     INTEGER NOT NULL,
    from_level  INTEGER NOT NULL CHECK (from_level >= 0),
    facility    TEXT NOT NULL CHECK (facility IN ('builder', 'lab', 'pet_house')),
    position    INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
) STRICT;
CREATE INDEX queue_item_tag ON queue_item (tag, position);

-- +migrate down
DROP TABLE IF EXISTS queue_item;
