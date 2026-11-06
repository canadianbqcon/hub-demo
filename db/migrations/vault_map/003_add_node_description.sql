-- Migration 003_add_node_description for vault_map.db
-- Generated: 2026-06-12
-- Purpose: a DURABLE store of AI-written one-line descriptions per node, keyed by
-- path. map_node is a cache that refresh() wipes and rewrites in full, so written
-- descriptions cannot live there. The walker (dashboard/hub/vault_map/db.py) reads
-- this table on refresh and prefers a description here over a canned by-type label,
-- but NEVER over an authored frontmatter `summary` or a folder's CLAUDE.md line
-- (source authority: authored content wins). content_sig (size:mtime) lets a future
-- re-sweep refresh only the descriptions of files that have changed.

-- +migrate up

CREATE TABLE node_description (
    path         TEXT PRIMARY KEY,           -- matches map_node.path (vault-rel; 'vault-code/...' for the sibling repo)
    description  TEXT NOT NULL,              -- the one-line purpose shown in the side panel
    source       TEXT,                       -- provenance, e.g. 'ai-sweep-2026-06-12'
    content_sig  TEXT,                        -- 'size:mtime' fingerprint for idempotent re-sweeps
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

-- +migrate down

DROP TABLE node_description;
