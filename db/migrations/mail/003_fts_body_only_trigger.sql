-- +migrate up
-- message_au reindexed the whole body on every label change (mark read, archive,
-- a sync's label history). Only the indexed columns now fire it.
DROP TRIGGER IF EXISTS message_au;
CREATE TRIGGER message_au AFTER UPDATE OF subject, from_name, from_addr, body_text ON message BEGIN
    INSERT INTO message_fts(message_fts, rowid, subject, from_name, from_addr, body_text)
    VALUES ('delete', old.rowid, old.subject, old.from_name, old.from_addr, old.body_text);
    INSERT INTO message_fts(rowid, subject, from_name, from_addr, body_text)
    VALUES (new.rowid, new.subject, new.from_name, new.from_addr, new.body_text);
END;

-- +migrate down
DROP TRIGGER IF EXISTS message_au;
CREATE TRIGGER message_au AFTER UPDATE ON message BEGIN
    INSERT INTO message_fts(message_fts, rowid, subject, from_name, from_addr, body_text)
    VALUES ('delete', old.rowid, old.subject, old.from_name, old.from_addr, old.body_text);
    INSERT INTO message_fts(rowid, subject, from_name, from_addr, body_text)
    VALUES (new.rowid, new.subject, new.from_name, new.from_addr, new.body_text);
END;
