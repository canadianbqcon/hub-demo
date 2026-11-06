-- Migration 005_refresh_log for book.db
-- Generated: 2026-10-22
--
-- Two times the book used to overwrite, now kept as history.
-- account_refresh: one row per account per sync, holding the Bridge's
-- balance-date (when SimpleFIN last refreshed that bank) and when we saw it.
-- account.balance_at still holds only the latest. seen_at is NULL only on rows
-- seeded from values read by hand before this log existed.
-- txn.first_seen_at: when a sync first wrote or adopted the row; never
-- rewritten (updated_at changes on every edit). NULL on rows older than this.

-- +migrate up

CREATE TABLE account_refresh (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES account(id),
    refreshed_at TEXT NOT NULL,
    seen_at      TEXT
) STRICT;
CREATE INDEX account_refresh_acct ON account_refresh(account_id, refreshed_at);
ALTER TABLE txn ADD COLUMN first_seen_at TEXT;

-- +migrate down

ALTER TABLE txn DROP COLUMN first_seen_at;
DROP TABLE account_refresh;
