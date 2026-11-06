-- +migrate up
-- A 3-4 word list title per subject line, written by Haiku after each sync
-- (mail/claude_actions.short_titles). Keyed by the subject text, so threads
-- sharing a subject share one title and a new subject gets its own.
CREATE TABLE IF NOT EXISTS short_title (
    subject    TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    model      TEXT,
    cost_usd   REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS short_title;
