-- +migrate up
-- A one-line Haiku summary per message, shown under the title in the mail list
-- in place of Gmail's snippet (mail/claude_actions.list_previews, run after each
-- sync). Keyed by message id: the list shows its thread's newest message's line.
CREATE TABLE IF NOT EXISTS list_preview (
    msg_id     TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    model      TEXT,
    cost_usd   REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS list_preview;
