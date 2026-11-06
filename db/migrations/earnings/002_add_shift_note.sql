-- vault-code/db/migrations/earnings/002_add_shift_note.sql
-- +migrate up
ALTER TABLE earnings_shifts ADD COLUMN note TEXT;

-- +migrate down
ALTER TABLE earnings_shifts DROP COLUMN note;
