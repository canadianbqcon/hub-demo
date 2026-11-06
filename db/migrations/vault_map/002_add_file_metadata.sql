-- Migration 002_add_file_metadata for vault_map.db
-- Generated: 2026-06-12
-- Purpose: carry the production port of the vault-map design session
-- (handoff 2026-06-12-123312-vault-map). Two changes:
--
--   1. Add per-node file metadata columns the new walker captures:
--        size      INTEGER  bytes (file = own size; folder = subtree sum)
--        mtime     TEXT     last-modified date 'YYYY-MM-DD' (folder = own mtime)
--        lines     INTEGER  line count for authored text files < 2 MB (else NULL)
--        ext       TEXT     lowercased extension incl. dot ('.md'); NULL if none
--        generated INTEGER  1 = tool-generated / derived (.git, caches, .pyc…)
--
--   2. node_function semantics expand from the old 5-function folder palette
--      (knowledge|ingest|apps|ops|governance) to the 10-bucket intrinsic-tell
--      model: knowledge, ingest, asset, code, data, config, governance,
--      records, misc, unclassified. node_function is an unconstrained TEXT
--      column (no CHECK), so this is a semantic change only — no DDL for it.
--      The walker rewrite (dashboard/hub/vault_map/db.py) owns the new
--      classifier; see docs/specs/2026-06-12-vault-map-production-design.md.
--
-- map_node is still a CACHE: refresh() wipes and repopulates in full, so these
-- columns are backfilled on the next refresh regardless of the DEFAULTs below.

-- +migrate up

ALTER TABLE map_node ADD COLUMN size      INTEGER;
ALTER TABLE map_node ADD COLUMN mtime     TEXT;
ALTER TABLE map_node ADD COLUMN lines     INTEGER;
ALTER TABLE map_node ADD COLUMN ext       TEXT;
ALTER TABLE map_node ADD COLUMN generated INTEGER NOT NULL DEFAULT 0;

-- +migrate down

-- SQLite cannot DROP COLUMN portably on a STRICT table across all versions.
-- To reverse: recreate map_node from the 001 schema and repopulate via refresh().
