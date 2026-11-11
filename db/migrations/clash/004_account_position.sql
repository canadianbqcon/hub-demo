-- +migrate up
-- Village order on the tracker tabs (he reorders them). A new village goes to the end.
ALTER TABLE account ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
UPDATE account SET position = (SELECT COUNT(*) FROM account a2
    WHERE a2.name COLLATE NOCASE < account.name COLLATE NOCASE
       OR (a2.name COLLATE NOCASE = account.name COLLATE NOCASE AND a2.tag < account.tag)) + 1;
CREATE TRIGGER IF NOT EXISTS account_position_last AFTER INSERT ON account WHEN NEW.position = 0
BEGIN
    UPDATE account SET position = (SELECT COALESCE(MAX(position), 0) + 1 FROM account) WHERE tag = NEW.tag;
END;

-- +migrate down
DROP TRIGGER IF EXISTS account_position_last;
ALTER TABLE account DROP COLUMN position;
