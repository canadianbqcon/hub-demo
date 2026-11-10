-- +migrate up
-- brief: newsletter-like mail the lane judges read-once. brief_entry keeps the captured text and the
-- filled summary after the email is trashed; brief_sender holds his per-domain Read / Unsubscribe choice.
ALTER TABLE gmail_item ADD COLUMN brief INTEGER;            -- NULL not judged, 0/1
CREATE TABLE brief_entry (
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL UNIQUE, msg_id TEXT NOT NULL,
  sender TEXT, domain TEXT, subject TEXT, received_at TEXT,
  state TEXT NOT NULL CHECK (state IN ('captured','ready','purged')),
  body TEXT, links_json TEXT,                                -- the capture
  title TEXT, points_json TEXT, picked_json TEXT,            -- the fill
  source TEXT CHECK (source IN ('model','fallback')),
  tries INTEGER NOT NULL DEFAULT 0, cost_usd REAL,
  created_at TEXT NOT NULL, deleted_at TEXT) STRICT;
CREATE INDEX idx_brief_entry_list ON brief_entry(state, deleted_at, received_at);
CREATE TABLE brief_sender (
  domain TEXT PRIMARY KEY, choice TEXT NOT NULL CHECK (choice IN ('read','unsub')),
  unsub_state TEXT CHECK (unsub_state IN ('done','unconfirmed')), updated_at TEXT NOT NULL) STRICT;
UPDATE gmail_item SET brief=1 WHERE id IN (51,326,333,334,385) AND kind IN ('newsletter','product announcement');
INSERT OR IGNORE INTO brief_sender VALUES ('theepochtimes.com','unsub',NULL,strftime('%Y-%m-%dT%H:%M:%SZ','now'));

-- +migrate down
DROP TABLE brief_sender;
DROP TABLE brief_entry;
ALTER TABLE gmail_item DROP COLUMN brief;
