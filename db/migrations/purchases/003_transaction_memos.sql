-- Migration 003_transaction_memos for purchases.db
-- Generated: 2026-06-01
-- Purpose: staging table for voice-captured transaction memos. Pending rows are
-- created at ingest time; linked rows carry the YNAB transaction id once matched.

-- +migrate up

CREATE TABLE transaction_memos (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript           TEXT    NOT NULL,
    recorded_at          TEXT    NOT NULL,
    lat                  REAL,
    lon                  REAL,
    location_label       TEXT    DEFAULT '',
    vendor_guess         TEXT    DEFAULT '',
    amount_guess         REAL,
    category_guess       TEXT    DEFAULT '',
    payment_method_guess TEXT    DEFAULT '',
    ynab_transaction_id  TEXT,
    status               TEXT    DEFAULT 'pending',
    created              TEXT    DEFAULT (datetime('now')),
    updated              TEXT    DEFAULT (datetime('now'))
) STRICT;

-- +migrate down

DROP TABLE transaction_memos;
