-- +migrate up
-- notify.db -- gitignored (data/notify.db), one per machine, written by any Hub
-- module through notify.post() and by the notify-push scheduler job. Timestamps
-- are UTC, YYYY-MM-DDTHH:MM:SSZ, so text order is time order. STRICT.

CREATE TABLE IF NOT EXISTS notification (
    id         INTEGER PRIMARY KEY,
    key        TEXT UNIQUE,
    source     TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT,
    url        TEXT,
    created_at TEXT NOT NULL,
    due_at     TEXT NOT NULL,
    read_at    TEXT,
    push_state TEXT NOT NULL DEFAULT 'none' CHECK (push_state IN
        ('none', 'pending', 'sending', 'sent', 'failed', 'skipped')),
    pushed_at  TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_notification_due ON notification(due_at);
CREATE INDEX IF NOT EXISTS idx_notification_push ON notification(push_state, due_at);

-- +migrate down
DROP INDEX IF EXISTS idx_notification_push;
DROP INDEX IF EXISTS idx_notification_due;
DROP TABLE IF EXISTS notification;
