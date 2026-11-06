-- +migrate up
-- details: two or three sentences of what an email actually says (versions, amounts, dates, what
-- changed), kept after the email is trashed so an inbox-summary page can report it later.
ALTER TABLE gmail_item ADD COLUMN details TEXT;

-- +migrate down
ALTER TABLE gmail_item DROP COLUMN details;
