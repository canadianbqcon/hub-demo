-- Migration 004_autocat for book.db
-- Generated: 2026-10-09
--
-- Haiku category suggestions, written by finances/autocat.py after each sync.
-- A high-confidence guess also sets category_id (and approves, except P2P
-- outflows and rideshares; pending holds are skipped until they post); a low one stays a suggestion for
-- /finance. suggested_at is the ISO time it was made; NULL means not yet sent.

-- +migrate up

ALTER TABLE txn ADD COLUMN suggested_category_id INTEGER REFERENCES category(id);
ALTER TABLE txn ADD COLUMN suggested_confidence TEXT CHECK (suggested_confidence IN ('high','low'));
ALTER TABLE txn ADD COLUMN suggested_at TEXT;

-- +migrate down

ALTER TABLE txn DROP COLUMN suggested_at;
ALTER TABLE txn DROP COLUMN suggested_confidence;
ALTER TABLE txn DROP COLUMN suggested_category_id;
