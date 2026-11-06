-- +migrate up
-- automations.db -- gitignored (data/automations.db), written hourly by the
-- gmail-lane job and only on the active machine, so it is never synced.
-- gmail_item: one row per Gmail message the lane has handled or proposed an
-- action for. lane_run: one row per job run. All tables STRICT.

CREATE TABLE IF NOT EXISTS gmail_item (
    id             INTEGER PRIMARY KEY,
    msg_id         TEXT NOT NULL UNIQUE,
    thread_id      TEXT,
    received_at    TEXT,
    sender         TEXT,
    domain         TEXT,
    subject        TEXT,
    summary        TEXT,
    action         TEXT,
    label          TEXT,
    confidence     TEXT,
    reason         TEXT,
    unsub_url      TEXT,
    unsub_one_click INTEGER NOT NULL DEFAULT 0,
    state          TEXT NOT NULL CHECK (state IN
        ('moved', 'proposed', 'done', 'rejected', 'undone', 'stale', 'unconfirmed', 'failed')),
    run_id         TEXT,
    cost_usd       REAL NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_gmail_item_state ON gmail_item(state);
CREATE INDEX IF NOT EXISTS idx_gmail_item_updated ON gmail_item(updated_at);

CREATE TABLE IF NOT EXISTS lane_run (
    run_id      TEXT PRIMARY KEY,
    job         TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    outcome     TEXT,
    counts_json TEXT,
    cost_usd    REAL NOT NULL DEFAULT 0
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS lane_run;
DROP INDEX IF EXISTS idx_gmail_item_updated;
DROP INDEX IF EXISTS idx_gmail_item_state;
DROP TABLE IF EXISTS gmail_item;
