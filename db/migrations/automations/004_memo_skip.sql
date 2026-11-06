-- +migrate up
-- memo_skip: finance rows he chose to leave without a memo (subscriptions, card payments).
-- The Automations page stops asking for their memo and the memo lane leaves them alone.
CREATE TABLE memo_skip (
    txn_uid    TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS memo_skip;
