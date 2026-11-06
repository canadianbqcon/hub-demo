-- +migrate up
-- (1) decision.lane gains 'voice-memo' (automations/voice_memo_lane.py). SQLite cannot alter a
--     CHECK, so the table is rebuilt with every row and id kept; nothing references it by FK.
-- (2) voice_memo_wait: voice memos the lane left for /recap (ambiguous, a guard refused, a
--     blocked action kind, malformed, failed partway). Keyed by file name plus mtime so an
--     edited memo is judged fresh; rows whose file is gone are pruned by the lane.
CREATE TABLE decision_new (
    id           INTEGER PRIMARY KEY,
    lane         TEXT NOT NULL CHECK (lane IN ('gmail', 'finance-category', 'finance-memo', 'voice-memo')),
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
INSERT INTO decision_new SELECT id, lane, ref, item_id, rule_key, made_at, made_by, action,
    changed_json, state, undo, reason, fixed_by, fix_key FROM decision;
DROP TABLE decision;
ALTER TABLE decision_new RENAME TO decision;
CREATE INDEX IF NOT EXISTS idx_decision_made ON decision(made_at);
CREATE INDEX IF NOT EXISTS idx_decision_state ON decision(state);

CREATE TABLE voice_memo_wait (
    name       TEXT NOT NULL,
    mtime      REAL NOT NULL,
    why        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (name, mtime)
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS voice_memo_wait;
DELETE FROM decision WHERE lane = 'voice-memo';
DELETE FROM rule_block WHERE lane = 'voice-memo';
CREATE TABLE decision_old (
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
INSERT INTO decision_old SELECT * FROM decision;
DROP TABLE decision;
ALTER TABLE decision_old RENAME TO decision;
CREATE INDEX IF NOT EXISTS idx_decision_made ON decision(made_at);
CREATE INDEX IF NOT EXISTS idx_decision_state ON decision(state);
