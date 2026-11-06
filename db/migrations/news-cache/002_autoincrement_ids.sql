-- +migrate up
-- clusters.id and items.id were plain INTEGER PRIMARY KEY, which SQLite is
-- free to reuse once the row holding the current max id is gone (a merge, the
-- 30-day prune, a manual delete). A reused cluster id makes an old alerts row
-- or an old digest's `[#id]` citation silently point at a different,
-- unrelated story. AUTOINCREMENT makes both ids monotonic for the life of the
-- database: an id, once handed out, is never handed out again.
--
-- Table rebuild (STRICT preserved, data copied) -- same pattern as
-- db/migrations/jobs/004_strict_applications_and_close_fields.sql.

PRAGMA foreign_keys = OFF;

CREATE TABLE clusters_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    section    TEXT NOT NULL,
    title      TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
) STRICT;

INSERT INTO clusters_new (id, section, title, first_seen, last_seen)
    SELECT id, section, title, first_seen, last_seen FROM clusters;

DROP TABLE clusters;
ALTER TABLE clusters_new RENAME TO clusters;
CREATE INDEX IF NOT EXISTS idx_clusters_section ON clusters(section, last_seen);

CREATE TABLE items_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL,
    guid         TEXT NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    cluster_id   INTEGER,
    pinned       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, guid)
) STRICT;

INSERT INTO items_new (id, source_id, guid, url, title, summary, published_at,
                        fetched_at, cluster_id, pinned)
    SELECT id, source_id, guid, url, title, summary, published_at, fetched_at,
           cluster_id, pinned FROM items;

DROP TABLE items;
ALTER TABLE items_new RENAME TO items;
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);

-- Any alert already orphaned (its cluster deleted before this migration ran)
-- is dead weight now that ids will never collide with a live cluster again.
DELETE FROM alerts WHERE cluster_id NOT IN (SELECT id FROM clusters);

PRAGMA foreign_keys = ON;

-- +migrate down
-- Reversing would mean the same rebuild without AUTOINCREMENT; nothing reads
-- rowid-reuse behavior on purpose, so there is no reason to ever run it.
