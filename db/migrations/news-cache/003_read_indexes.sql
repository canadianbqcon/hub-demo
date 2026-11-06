-- +migrate up
-- Read-path indexes. Measured 2026-10-13 against a 54k-item cache on /mnt/c,
-- where every page read crosses the WSL file bridge:
--   * the Home news card counted today's clusters by walking every reporting
--     item through the (source_id, guid) index and then fetching each row for
--     cluster_id: 11.6s. It now starts from clusters.last_seen and checks
--     membership in (cluster_id, source_id) without touching the item rows.
--   * /news/api/status measures each source's 7-day median gap, one query per
--     source on (source_id, published_at): 5.2s with no index to cover it.
-- (cluster_id, source_id) has cluster_id as its prefix, so it replaces
-- idx_items_cluster rather than sitting beside it.

CREATE INDEX IF NOT EXISTS idx_items_cluster_source ON items(cluster_id, source_id);
DROP INDEX IF EXISTS idx_items_cluster;
CREATE INDEX IF NOT EXISTS idx_items_source_published ON items(source_id, published_at);
CREATE INDEX IF NOT EXISTS idx_clusters_last_seen ON clusters(last_seen);

-- +migrate down
DROP INDEX IF EXISTS idx_clusters_last_seen;
DROP INDEX IF EXISTS idx_items_source_published;
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);
DROP INDEX IF EXISTS idx_items_cluster_source;
