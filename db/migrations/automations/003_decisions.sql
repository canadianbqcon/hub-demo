-- +migrate up
-- decision: one durable row per effect any lane has made or is making, written
-- pending before the effect and finished after (automations/decisions.py).
-- changed_json is {"field": [before, after]}. gmail_note: Sam's standing notes.
-- rule_block: a (domain, kind) or payee that undo blocked until three fresh human
-- answers agree; the unblock is computed from answers, never stored.
-- memo_hold / memo_draft: the finance memo lane's skip list and drafts.
CREATE TABLE IF NOT EXISTS decision (
    id           INTEGER PRIMARY KEY,
    lane         TEXT NOT NULL CHECK (lane IN ('gmail', 'finance-category', 'finance-memo')),
    ref          TEXT NOT NULL,
    item_id      INTEGER,
    rule_key     TEXT,
    made_at      TEXT NOT NULL,
    made_by      TEXT NOT NULL CHECK (made_by IN ('auto', 'sam')),
    action       TEXT NOT NULL,
    changed_json TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN
        ('pending', 'applied', 'failed', 'unknown', 'undone', 'fixed')),
    undo         TEXT NOT NULL CHECK (undo IN ('reversible', 'expires', 'none')),
    reason       TEXT,
    fixed_by     INTEGER,
    fix_key      TEXT UNIQUE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_decision_made ON decision(made_at);
CREATE INDEX IF NOT EXISTS idx_decision_state ON decision(state);

CREATE TABLE IF NOT EXISTS gmail_note (
    id         INTEGER PRIMARY KEY,
    domain     TEXT,
    kind       TEXT,
    text       TEXT NOT NULL,
    op         TEXT,
    created_at TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE TABLE IF NOT EXISTS rule_block (
    lane          TEXT NOT NULL,
    rule_key      TEXT NOT NULL,
    blocked_since TEXT NOT NULL,
    PRIMARY KEY (lane, rule_key)
) STRICT;

CREATE TABLE IF NOT EXISTS memo_hold (
    txn_uid    TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS memo_draft (
    txn_uid       TEXT PRIMARY KEY,
    memo          TEXT NOT NULL,
    evidence_json TEXT,
    created_at    TEXT NOT NULL
) STRICT;

ALTER TABLE gmail_item ADD COLUMN kind TEXT;
ALTER TABLE gmail_item ADD COLUMN judged_at TEXT;

-- +migrate down
ALTER TABLE gmail_item DROP COLUMN judged_at;
ALTER TABLE gmail_item DROP COLUMN kind;
DROP TABLE IF EXISTS memo_draft;
DROP TABLE IF EXISTS memo_hold;
DROP TABLE IF EXISTS rule_block;
DROP TABLE IF EXISTS gmail_note;
DROP INDEX IF EXISTS idx_decision_state;
DROP INDEX IF EXISTS idx_decision_made;
DROP TABLE IF EXISTS decision;
