-- Migration 003_payee_short_name for book.db
-- Generated: 2026-10-08
--
-- A human-readable title for a payee ("NY Unemployment" for "NYS DOL UI DD UI DD
-- PPD ID: 1133886111"). NULL means the bank name already reads fine. The
-- /finances page shows short_name and flips to name on click.

-- +migrate up

ALTER TABLE payee ADD COLUMN short_name TEXT;

-- +migrate down

ALTER TABLE payee DROP COLUMN short_name;
