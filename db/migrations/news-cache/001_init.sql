-- +migrate up
-- news-cache.db -- gitignored, rebuildable: items, clusters, articles, alerts,
-- poll_state. Everything the 15-minute poll writes; losing this file costs at
-- most 36 hours of grouping and any manual regroupings in that window (rebuilt
-- on the next poll). Config lives in the tracked data/news.db instead, see
-- db/migrations/news/001_init.sql. All tables STRICT.

CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY,
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

CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);

CREATE TABLE IF NOT EXISTS clusters (
    id         INTEGER PRIMARY KEY,
    section    TEXT NOT NULL,
    title      TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_clusters_section ON clusters(section, last_seen);

-- item_id is the PK, not a surrogate id, so a cached article is 1:1 with the item
-- it was extracted from and a second read just overwrites the cache in place.
CREATE TABLE IF NOT EXISTS articles (
    item_id    INTEGER PRIMARY KEY,
    text       TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'ok'
) STRICT;

-- One row per cluster, so "already alerted" is a lookup, not a scan.
CREATE TABLE IF NOT EXISTS alerts (
    cluster_id   INTEGER PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    reason       TEXT NOT NULL DEFAULT '',
    qualified_at TEXT NOT NULL,
    sent_at      TEXT
) STRICT;

-- Per-source fetch state, plus two pseudo-rows keyed '_run' (15-minute feed
-- cadence) and '_topics' (60-minute topic-feed cadence) reusing the same
-- source_id column rather than a second table.
CREATE TABLE IF NOT EXISTS poll_state (
    source_id            TEXT PRIMARY KEY,
    etag                 TEXT,
    last_modified        TEXT,
    last_ok_at           TEXT,
    last_item_at         TEXT,
    last_error           TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_run_at          TEXT
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS poll_state;
DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS articles;
DROP INDEX IF EXISTS idx_clusters_section;
DROP TABLE IF EXISTS clusters;
DROP INDEX IF EXISTS idx_items_cluster;
DROP TABLE IF EXISTS items;
