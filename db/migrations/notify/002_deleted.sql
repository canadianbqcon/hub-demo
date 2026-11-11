-- +migrate up
-- deleted_at: set when he deletes a row from the bell, or when the thing it
-- points at is no longer waiting on him (notify.resolve). The row stays as a
-- tombstone so a source that posts the same key again does not bring it back;
-- read_at is set with it, so the 30-day prune removes it.
ALTER TABLE notification ADD COLUMN deleted_at TEXT;

-- +migrate down
ALTER TABLE notification DROP COLUMN deleted_at;
