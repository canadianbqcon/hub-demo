-- Migration 001_initial for vault_map.db
-- Generated: 2026-06-03
-- Onboarded via wiki/decisions/onboard-vault-map.md
--
-- This is a FRESH-DB migration (the database does not exist yet), so apply with:
--     python data/migrate.py up vault_map
-- (NOT `baseline` — baseline is only for the four pre-Phase-1 databases whose
--  tables already existed. schema_migrations is created by migrate.py itself.)
--
-- DERIVED FROM: the vault filesystem. map_node is a CACHE — it is wiped and
-- rewritten in full on every refresh (see dashboard/hub/vault_map/db.py
-- refresh()). No SCD/history: the user chose cache-overwrite semantics.

-- +migrate up

CREATE TABLE map_node (
    path          TEXT PRIMARY KEY,            -- path relative to vault root ('.' = root)
    parent_path   TEXT,                        -- parent's path; NULL only for the root node
    name          TEXT NOT NULL,               -- display label (folder or file name)
    node_kind     TEXT NOT NULL,               -- 'folder' | 'file'
    wiki_type     TEXT,                        -- wiki node type (concept/decision/...) for wiki .md files
    node_function TEXT,                        -- knowledge|ingest|apps|ops|governance (inherited from top folder)
    purpose       TEXT,                        -- the qualitative one-line summary the side panel shows
    file_count    INTEGER NOT NULL DEFAULT 0,  -- count of files in this folder's subtree (0 for files)
    depth         INTEGER NOT NULL DEFAULT 0,  -- nesting depth from root (root = 0)
    wiki_slug     TEXT,                        -- cross-format ref (contract rule): rel path minus .md, wiki files only
    generated_at  TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX idx_map_node_parent ON map_node(parent_path);

-- +migrate down

DROP INDEX idx_map_node_parent;
DROP TABLE map_node;
