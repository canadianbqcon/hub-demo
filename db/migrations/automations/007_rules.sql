-- +migrate up
-- rule: every learned rule (Gmail notes and streaks, file-without-asking senders, finance
-- payee history). Lanes act only on state='confirmed'; rev is bumped on every edit or state
-- change so a stale tab or an in-flight effect can tell the row moved (automations/rules.py).
-- gmail_note gains per-note scope judgement; decision records which rule made an effect.
CREATE TABLE IF NOT EXISTS rule (
    id            INTEGER PRIMARY KEY,
    lane          TEXT NOT NULL CHECK (lane IN ('gmail', 'finance-category')),
    rule_key      TEXT NOT NULL,
    state         TEXT NOT NULL CHECK (state IN ('proposed', 'confirmed', 'off', 'rejected')),
    rev           INTEGER NOT NULL DEFAULT 1,
    kind_of_rule  TEXT NOT NULL CHECK (kind_of_rule IN
        ('fixed_action', 'files_without_asking', 'instruction')),
    action        TEXT,
    target        TEXT,
    note          TEXT,
    op            TEXT,
    source        TEXT NOT NULL CHECK (source IN ('note', 'streak', 'approved_sender', 'payee_history')),
    source_ref    TEXT NOT NULL,
    evidence_json TEXT,
    replaces      INTEGER,
    reason        TEXT,
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    updated_at    TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_rule_confirmed ON rule(lane, rule_key, source)
    WHERE state = 'confirmed' AND source != 'note';
CREATE UNIQUE INDEX IF NOT EXISTS ux_rule_proposed ON rule(lane, rule_key, source)
    WHERE state = 'proposed' AND source != 'note';
CREATE INDEX IF NOT EXISTS idx_rule_ref ON rule(lane, source, source_ref);
CREATE INDEX IF NOT EXISTS idx_rule_state ON rule(state);

ALTER TABLE gmail_note ADD COLUMN item_id INTEGER;
ALTER TABLE gmail_note ADD COLUMN scope TEXT CHECK (scope IN ('once', 'standing', 'both'));
ALTER TABLE gmail_note ADD COLUMN judged_at TEXT;
ALTER TABLE gmail_note ADD COLUMN tries INTEGER NOT NULL DEFAULT 0;
ALTER TABLE gmail_note ADD COLUMN button TEXT;
ALTER TABLE gmail_note ADD COLUMN rule_id INTEGER;

ALTER TABLE decision ADD COLUMN rule_id INTEGER;
ALTER TABLE decision ADD COLUMN rule_rev INTEGER;

-- +migrate down
ALTER TABLE decision DROP COLUMN rule_rev;
ALTER TABLE decision DROP COLUMN rule_id;
ALTER TABLE gmail_note DROP COLUMN rule_id;
ALTER TABLE gmail_note DROP COLUMN button;
ALTER TABLE gmail_note DROP COLUMN tries;
ALTER TABLE gmail_note DROP COLUMN judged_at;
ALTER TABLE gmail_note DROP COLUMN scope;
ALTER TABLE gmail_note DROP COLUMN item_id;
DROP INDEX IF EXISTS idx_rule_state;
DROP INDEX IF EXISTS idx_rule_ref;
DROP INDEX IF EXISTS ux_rule_proposed;
DROP INDEX IF EXISTS ux_rule_confirmed;
DROP TABLE IF EXISTS rule;
