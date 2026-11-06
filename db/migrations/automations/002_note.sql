-- +migrate up
-- note: Sam's free-text answer from the Automations page's "other" box.
-- A proposed row with a note is handed to the next /gmail run, which carries
-- it out and marks the row done.
ALTER TABLE gmail_item ADD COLUMN note TEXT;

-- +migrate down
ALTER TABLE gmail_item DROP COLUMN note;
