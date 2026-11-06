-- Migration 002_sign_calibrated for book.db
-- Generated: 2026-10-07
--
-- simplefin.sync calibrates each account's balance_sign once, on the first
-- balance big enough to read. The done-flag used to be an "info: balance sign"
-- note in sync_run.errors, which could be written by a run whose ingest rolled
-- back. The flag now lives on the account and is set in the same transaction as
-- the sign itself.
--
-- The backfill marks accounts the old rule already counted as calibrated (a
-- note naming them in any sync_run). A fresh DB has no sync_run rows, so it
-- touches nothing there.

-- +migrate up

ALTER TABLE account ADD COLUMN sign_calibrated INTEGER NOT NULL DEFAULT 0
    CHECK (sign_calibrated IN (0, 1));

UPDATE account SET sign_calibrated = 1
WHERE EXISTS (
    SELECT 1 FROM sync_run r, json_each(r.errors) e
    WHERE e.value LIKE 'info: balance sign % for ' || account.name
);

-- +migrate down

ALTER TABLE account DROP COLUMN sign_calibrated;
