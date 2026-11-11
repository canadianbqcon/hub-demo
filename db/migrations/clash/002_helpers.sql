-- +migrate up
-- Helper huts (Builder's Apprentice, Lab Assistant, Alchemist, Prospector) from the export's `helpers`.
-- ready_at: when the helper can work again (export timestamp + helper_cooldown); NULL when unknown.
CREATE TABLE IF NOT EXISTS helper (
    tag      TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    data_id  INTEGER NOT NULL,
    level    INTEGER NOT NULL CHECK (level > 0),
    ready_at TEXT,
    PRIMARY KEY (tag, data_id)
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS helper;
